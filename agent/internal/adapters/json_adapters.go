package adapters

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/zuens2020/mcp-relay/agent/internal/fsutil"
	"github.com/zuens2020/mcp-relay/agent/internal/paths"
)

// ServerConfig is the canonical rendered MCP server entry.
type ServerConfig map[string]any

type Adapter interface {
	Name() string
	Apply(r *paths.Resolver, servers map[string]ServerConfig) error
	Diff(r *paths.Resolver, servers map[string]ServerConfig) (string, error)
}

func loadManaged(r *paths.Resolver, target string) (map[string]bool, error) {
	p := filepath.Join(r.ManagedDir(), target+".json")
	b, err := os.ReadFile(p)
	if err != nil {
		if os.IsNotExist(err) {
			return map[string]bool{}, nil
		}
		return nil, err
	}
	var ids []string
	if err := json.Unmarshal(b, &ids); err != nil {
		return nil, err
	}
	out := map[string]bool{}
	for _, id := range ids {
		out[id] = true
	}
	return out, nil
}

func saveManaged(r *paths.Resolver, target string, ids []string) error {
	if r.Mode == paths.ModeDryRun {
		return nil
	}
	p := filepath.Join(r.ManagedDir(), target+".json")
	if err := os.MkdirAll(r.ManagedDir(), 0o755); err != nil {
		return err
	}
	if err := r.AssertWritable(p); err != nil {
		return err
	}
	b, err := json.MarshalIndent(ids, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(p, b, 0o600)
}

func mergeJSONMCP(existing map[string]any, managed map[string]bool, incoming map[string]ServerConfig) (map[string]any, []string) {
	if existing == nil {
		existing = map[string]any{}
	}
	mcp, _ := existing["mcpServers"].(map[string]any)
	if mcp == nil {
		mcp = map[string]any{}
	}
	// remove previously managed that are no longer in incoming
	for id := range managed {
		if _, keep := incoming[id]; !keep {
			delete(mcp, id)
		}
	}
	ids := make([]string, 0, len(incoming))
	for id, cfg := range incoming {
		mcp[id] = map[string]any(cfg)
		ids = append(ids, id)
	}
	existing["mcpServers"] = mcp
	return existing, ids
}

func readJSONFile(path string) (map[string]any, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return map[string]any{}, nil
		}
		return nil, err
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		return nil, err
	}
	if m == nil {
		m = map[string]any{}
	}
	return m, nil
}

func writeJSON(r *paths.Resolver, path string, doc map[string]any) error {
	b, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return err
	}
	b = append(b, '\n')
	return fsutil.AtomicWrite(r, path, b)
}

// --- Cursor ---

type CursorAdapter struct{}

func (CursorAdapter) Name() string { return "cursor" }

func (a CursorAdapter) Apply(r *paths.Resolver, servers map[string]ServerConfig) error {
	path, err := r.MCPPath("cursor")
	if err != nil {
		return err
	}
	doc, err := readJSONFile(path)
	if err != nil {
		return err
	}
	managed, err := loadManaged(r, "cursor")
	if err != nil {
		return err
	}
	doc, ids := mergeJSONMCP(doc, managed, servers)
	if err := writeJSON(r, path, doc); err != nil {
		return err
	}
	return saveManaged(r, "cursor", ids)
}

func (a CursorAdapter) Diff(r *paths.Resolver, servers map[string]ServerConfig) (string, error) {
	path, _ := r.MCPPath("cursor")
	doc, _ := readJSONFile(path)
	want, _ := mergeJSONMCP(cloneMap(doc), map[string]bool{}, servers)
	b, _ := json.MarshalIndent(map[string]any{"path": path, "would": want["mcpServers"]}, "", "  ")
	return string(b), nil
}

// --- Pi ---

type PiAdapter struct{}

func (PiAdapter) Name() string { return "pi" }

func (a PiAdapter) Apply(r *paths.Resolver, servers map[string]ServerConfig) error {
	path, err := r.MCPPath("pi")
	if err != nil {
		return err
	}
	doc, err := readJSONFile(path)
	if err != nil {
		return err
	}
	managed, err := loadManaged(r, "pi")
	if err != nil {
		return err
	}
	doc, ids := mergeJSONMCP(doc, managed, servers)
	if err := writeJSON(r, path, doc); err != nil {
		return err
	}
	return saveManaged(r, "pi", ids)
}

func (a PiAdapter) Diff(r *paths.Resolver, servers map[string]ServerConfig) (string, error) {
	path, _ := r.MCPPath("pi")
	doc, _ := readJSONFile(path)
	want, _ := mergeJSONMCP(cloneMap(doc), map[string]bool{}, servers)
	b, _ := json.MarshalIndent(map[string]any{"path": path, "would": want["mcpServers"]}, "", "  ")
	return string(b), nil
}

// --- Claude Code ---

type ClaudeAdapter struct{}

func (ClaudeAdapter) Name() string { return "claude-code" }

func (a ClaudeAdapter) Apply(r *paths.Resolver, servers map[string]ServerConfig) error {
	path, err := r.MCPPath("claude-code")
	if err != nil {
		return err
	}
	doc, err := readJSONFile(path)
	if err != nil {
		return err
	}
	// Preserve all non-mcpServers keys (oauth, projects, caches).
	managed, err := loadManaged(r, "claude-code")
	if err != nil {
		return err
	}
	mcp, _ := doc["mcpServers"].(map[string]any)
	if mcp == nil {
		mcp = map[string]any{}
	}
	for id := range managed {
		if _, keep := servers[id]; !keep {
			delete(mcp, id)
		}
	}
	ids := make([]string, 0, len(servers))
	for id, cfg := range servers {
		mcp[id] = map[string]any(cfg)
		ids = append(ids, id)
	}
	doc["mcpServers"] = mcp
	if err := writeJSON(r, path, doc); err != nil {
		return err
	}
	return saveManaged(r, "claude-code", ids)
}

func (a ClaudeAdapter) Diff(r *paths.Resolver, servers map[string]ServerConfig) (string, error) {
	path, _ := r.MCPPath("claude-code")
	doc, _ := readJSONFile(path)
	mcp, _ := doc["mcpServers"].(map[string]any)
	b, _ := json.MarshalIndent(map[string]any{"path": path, "current": mcp, "incoming": servers}, "", "  ")
	return string(b), nil
}

func cloneMap(m map[string]any) map[string]any {
	b, _ := json.Marshal(m)
	var out map[string]any
	_ = json.Unmarshal(b, &out)
	if out == nil {
		out = map[string]any{}
	}
	return out
}

func All() map[string]Adapter {
	return map[string]Adapter{
		"cursor":      CursorAdapter{},
		"pi":          PiAdapter{},
		"claude-code": ClaudeAdapter{},
		"hermes":      HermesAdapter{},
		"codex":       CodexAdapter{},
	}
}

func Get(name string) (Adapter, error) {
	a, ok := All()[name]
	if !ok {
		return nil, fmt.Errorf("unknown adapter %s", name)
	}
	return a, nil
}
