package adapters

import (
	"fmt"
	"os"
	"strings"

	"github.com/pelletier/go-toml/v2"
	"github.com/zuens2020/mcp-relay/agent/internal/fsutil"
	"github.com/zuens2020/mcp-relay/agent/internal/paths"
)

type CodexAdapter struct{}

func (CodexAdapter) Name() string { return "codex" }

// toCodexEntry maps canonical JSON-ish fields to Codex TOML fields.
func toCodexEntry(cfg ServerConfig) map[string]any {
	out := map[string]any{}
	for k, v := range cfg {
		switch k {
		case "headers":
			out["http_headers"] = v
		default:
			out[k] = v
		}
	}
	return out
}

func (a CodexAdapter) Apply(r *paths.Resolver, servers map[string]ServerConfig) error {
	path, err := r.MCPPath("codex")
	if err != nil {
		return err
	}
	doc := map[string]any{}
	if b, err := os.ReadFile(path); err == nil {
		if err := toml.Unmarshal(b, &doc); err != nil {
			return fmt.Errorf("parse codex config: %w", err)
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	if doc == nil {
		doc = map[string]any{}
	}
	managed, err := loadManaged(r, "codex")
	if err != nil {
		return err
	}

	mcp, _ := doc["mcp_servers"].(map[string]any)
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
		mcp[id] = toCodexEntry(cfg)
		ids = append(ids, id)
	}
	doc["mcp_servers"] = mcp

	out, err := toml.Marshal(doc)
	if err != nil {
		return err
	}
	// Preserve a header comment if file started with model= style — toml marshal is fine for MVP.
	_ = strings.TrimSpace(string(out))
	if err := fsutil.AtomicWrite(r, path, out); err != nil {
		return err
	}
	return saveManaged(r, "codex", ids)
}

func (a CodexAdapter) Diff(r *paths.Resolver, servers map[string]ServerConfig) (string, error) {
	path, _ := r.MCPPath("codex")
	return fmt.Sprintf("path=%s incoming_servers=%d", path, len(servers)), nil
}
