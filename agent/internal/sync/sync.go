package syncer

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/zuens2020/mcp-relay/agent/internal/adapters"
	"github.com/zuens2020/mcp-relay/agent/internal/backup"
	"github.com/zuens2020/mcp-relay/agent/internal/config"
	"github.com/zuens2020/mcp-relay/agent/internal/detect"
	"github.com/zuens2020/mcp-relay/agent/internal/fsutil"
	"github.com/zuens2020/mcp-relay/agent/internal/paths"
)

type Client struct {
	HTTP *http.Client
	Cfg  *config.Config
	Res  *paths.Resolver
}

func New(cfg *config.Config, res *paths.Resolver) *Client {
	return &Client{
		HTTP: &http.Client{Timeout: 60 * time.Second},
		Cfg:  cfg,
		Res:  res,
	}
}

type registerResp struct {
	DeviceID    string   `json:"device_id"`
	DeviceToken string   `json:"device_token"`
	Profile     string   `json:"profile"`
	Targets     []string `json:"targets"`
}

type latestResp struct {
	ID        string         `json:"id"`
	ETag      string         `json:"etag"`
	Artifact  map[string]any `json:"artifact"`
	Changelog string         `json:"changelog"`
}

func unionTargets(a, b []string) []string {
	seen := map[string]struct{}{}
	var out []string
	for _, xs := range [][]string{a, b} {
		for _, t := range xs {
			t = strings.TrimSpace(t)
			if t == "" {
				continue
			}
			if _, ok := seen[t]; ok {
				continue
			}
			seen[t] = struct{}{}
			out = append(out, t)
		}
	}
	return out
}

func (c *Client) Register(det detect.Result) error {
	profile := c.Cfg.Profile
	if profile == "" {
		profile = det.Profile
	}
	// Always union configured targets with freshly detected agents so a stale
	// config.yaml (e.g. targets: [pi]) does not drop cursor/codex/etc.
	targets := unionTargets(c.Cfg.Targets, det.Targets)
	host, _ := os.Hostname()
	body := map[string]any{
		"device_id":     c.Cfg.DeviceID,
		"profile":       profile,
		"targets":       targets,
		"hostname":      host,
		"agent_version": c.Cfg.AgentVersion,
		"detected":      det.Detected,
	}
	var out registerResp
	if err := c.postJSON("/api/v1/devices/register", body, nil, &out); err != nil {
		return err
	}
	c.Cfg.DeviceID = out.DeviceID
	c.Cfg.DeviceToken = out.DeviceToken
	c.Cfg.Profile = out.Profile
	c.Cfg.Targets = out.Targets
	return config.Save(c.Res.ConfigPath(), c.Cfg)
}

func (c *Client) Sync(skillsRoot string) error {
	if c.Cfg.DeviceToken == "" {
		return fmt.Errorf("not registered; run relay-agent register first")
	}
	if c.Res.Mode == paths.ModeLive && !c.Cfg.AllowLiveWrites {
		return fmt.Errorf("live mode requires allow_live_writes: true in %s", c.Res.ConfigPath())
	}

	det := detect.Run(c.Res)
	targets := unionTargets(c.Cfg.Targets, det.Targets)
	if len(targets) == 0 {
		return fmt.Errorf("no agent targets detected; install an agent or set targets in config")
	}
	c.Cfg.Targets = targets
	// Refresh server-side targets/detection so admin UI lists every local agent.
	if err := c.Register(det); err != nil {
		return fmt.Errorf("refresh register: %w", err)
	}
	targets = c.Cfg.Targets

	// 1) backup before any mutation
	bakDir, err := backup.Run(c.Res, targets)
	if err != nil {
		return fmt.Errorf("backup: %w", err)
	}
	fmt.Printf("backup: %s\n", bakDir)

	// 2) bootstrap empty server configs from local
	if c.Res.Mode != paths.ModeDryRun {
		for _, t := range targets {
			br, err := c.BootstrapTarget(t)
			if err != nil {
				return fmt.Errorf("bootstrap %s: %w", t, err)
			}
			if br != nil {
				fmt.Printf("bootstrap %s: %s", t, br.Status)
				if br.Reason != "" {
					fmt.Printf(" (%s)", br.Reason)
				}
				if br.ServerCount > 0 {
					fmt.Printf(" servers=%d", br.ServerCount)
				}
				fmt.Println()
			}
		}
	}

	profile := c.Cfg.Profile
	q := url.Values{}
	q.Set("profile", profile)
	q.Set("targets", strings.Join(targets, ","))
	var latest latestResp
	if err := c.getJSON("/api/v1/releases/latest?"+q.Encode(), &latest); err != nil {
		return err
	}
	art := latest.Artifact
	byTarget, _ := art["targets"].(map[string]any)
	detail := map[string]any{"targets": map[string]any{}, "backup": bakDir}

	for _, t := range targets {
		raw, _ := byTarget[t].(map[string]any)
		servers := map[string]adapters.ServerConfig{}
		for id, v := range raw {
			if m, ok := v.(map[string]any); ok {
				servers[id] = adapters.ServerConfig(m)
			}
		}
		ad, err := adapters.Get(t)
		if err != nil {
			return err
		}
		if c.Res.Mode == paths.ModeDryRun {
			diff, _ := ad.Diff(c.Res, servers)
			fmt.Println(diff)
			continue
		}
		if err := ad.Apply(c.Res, servers); err != nil {
			_ = c.report(latest.ID, false, map[string]any{"error": err.Error(), "target": t, "backup": bakDir})
			return fmt.Errorf("apply %s: %w", t, err)
		}
		detail["targets"].(map[string]any)[t] = len(servers)
	}

	// skills
	if skills, ok := art["skills"].([]any); ok && c.Res.Mode != paths.ModeDryRun {
		for _, s := range skills {
			sm, ok := s.(map[string]any)
			if !ok {
				continue
			}
			id, _ := sm["id"].(string)
			relPath, _ := sm["path"].(string)
			tmap, _ := sm["targets"].(map[string]any)
			src := filepath.Join(skillsRoot, relPath)
			if skillsRoot == "" || !dirExists(src) {
				continue
			}
			for _, t := range targets {
				if _, ok := tmap[t]; !ok && len(tmap) > 0 {
					continue
				}
				dst, err := c.Res.SkillsPath(t, id)
				if err != nil {
					return err
				}
				if err := fsutil.CopyDir(src, dst, c.Res); err != nil {
					return fmt.Errorf("skill %s -> %s: %w", id, t, err)
				}
			}
		}
	}

	state := map[string]any{"last_release_id": latest.ID, "synced_at": time.Now().Format(time.RFC3339), "backup": bakDir}
	sb, _ := json.MarshalIndent(state, "", "  ")
	if c.Res.Mode != paths.ModeDryRun {
		_ = fsutil.AtomicWrite(c.Res, c.Res.StatePath(), append(sb, '\n'))
	}
	_ = c.report(latest.ID, true, detail)
	fmt.Printf("synced release %s mode=%s home=%s\n", latest.ID, c.Res.Mode, c.Res.Home())
	return nil
}

// ApplyRelease fetches a release bundle and applies it locally (used by WebSocket push).
func (c *Client) ApplyRelease(releaseID string, targets []string, skillsRoot string) error {
	if c.Cfg.DeviceToken == "" {
		return fmt.Errorf("not registered")
	}
	if len(targets) == 0 {
		targets = c.Cfg.Targets
	}
	var bundle struct {
		Artifact map[string]any `json:"artifact"`
	}
	if err := c.getJSON("/api/v1/releases/"+releaseID+"/bundle", &bundle); err != nil {
		return err
	}
	art := bundle.Artifact
	byTarget, _ := art["targets"].(map[string]any)
	detail := map[string]any{"targets": map[string]any{}, "release_id": releaseID}

	for _, t := range targets {
		raw, _ := byTarget[t].(map[string]any)
		servers := map[string]adapters.ServerConfig{}
		for id, v := range raw {
			if m, ok := v.(map[string]any); ok {
				servers[id] = adapters.ServerConfig(m)
			}
		}
		ad, err := adapters.Get(t)
		if err != nil {
			return err
		}
		if c.Res.Mode == paths.ModeDryRun {
			diff, _ := ad.Diff(c.Res, servers)
			fmt.Println(diff)
			continue
		}
		if err := ad.Apply(c.Res, servers); err != nil {
			_ = c.report(releaseID, false, map[string]any{"error": err.Error(), "target": t})
			return fmt.Errorf("apply %s: %w", t, err)
		}
		detail["targets"].(map[string]any)[t] = len(servers)
	}

	if skills, ok := art["skills"].([]any); ok && c.Res.Mode != paths.ModeDryRun && skillsRoot != "" {
		for _, s := range skills {
			sm, ok := s.(map[string]any)
			if !ok {
				continue
			}
			id, _ := sm["id"].(string)
			relPath, _ := sm["path"].(string)
			tmap, _ := sm["targets"].(map[string]any)
			src := filepath.Join(skillsRoot, relPath)
			if !dirExists(src) {
				continue
			}
			for _, t := range targets {
				if _, ok := tmap[t]; !ok && len(tmap) > 0 {
					continue
				}
				dst, err := c.Res.SkillsPath(t, id)
				if err != nil {
					return err
				}
				if err := fsutil.CopyDir(src, dst, c.Res); err != nil {
					return fmt.Errorf("skill %s -> %s: %w", id, t, err)
				}
			}
		}
	}

	state := map[string]any{"last_release_id": releaseID, "synced_at": time.Now().Format(time.RFC3339), "via": "push"}
	sb, _ := json.MarshalIndent(state, "", "  ")
	if c.Res.Mode != paths.ModeDryRun {
		_ = fsutil.AtomicWrite(c.Res, c.Res.StatePath(), append(sb, '\n'))
	}
	_ = c.report(releaseID, true, detail)
	return nil
}

func dirExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.IsDir()
}

func (c *Client) report(releaseID string, ok bool, detail map[string]any) error {
	body := map[string]any{"release_id": releaseID, "ok": ok, "detail": detail}
	return c.postJSON("/api/v1/devices/me/sync-report", body, map[string]string{
		"Authorization": "Bearer " + c.Cfg.DeviceToken,
	}, nil)
}

func (c *Client) ClearRegistration(reason string) {
	c.clearRegistration(reason)
}

func (c *Client) clearRegistration(reason string) {
	c.Cfg.DeviceToken = ""
	c.Cfg.DeviceID = ""
	c.Cfg.RelayURL = ""
	_ = config.Save(c.Res.ConfigPath(), c.Cfg)
	fmt.Fprintf(os.Stderr, "registration cleared (%s). Re-run: mcp-relay init --url <relay-url>\n", reason)
}

func (c *Client) handleAuthFailure(status int, body string) error {
	if status == http.StatusUnauthorized || status == http.StatusForbidden {
		c.clearRegistration(fmt.Sprintf("HTTP %d", status))
		return fmt.Errorf("device revoked or unauthorized (%d): %s — run mcp-relay init --url <relay-url>", status, body)
	}
	return nil
}

func (c *Client) getJSON(path string, out any) error {
	req, err := http.NewRequest(http.MethodGet, strings.TrimRight(c.Cfg.RelayURL, "/")+path, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.Cfg.DeviceToken)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		if err := c.handleAuthFailure(resp.StatusCode, string(b)); err != nil {
			return err
		}
		return fmt.Errorf("GET %s: %s: %s", path, resp.Status, string(b))
	}
	if out == nil {
		return nil
	}
	return json.Unmarshal(b, out)
}

func (c *Client) postJSON(path string, body any, headers map[string]string, out any) error {
	b, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodPost, strings.TrimRight(c.Cfg.RelayURL, "/")+path, bytes.NewReader(b))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	if c.Cfg.DeviceToken != "" && req.Header.Get("Authorization") == "" {
		req.Header.Set("Authorization", "Bearer "+c.Cfg.DeviceToken)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	rb, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		if err := c.handleAuthFailure(resp.StatusCode, string(rb)); err != nil {
			return err
		}
		return fmt.Errorf("POST %s: %s: %s", path, resp.Status, string(rb))
	}
	if out == nil {
		return nil
	}
	return json.Unmarshal(rb, out)
}
