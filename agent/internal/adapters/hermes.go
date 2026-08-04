package adapters

import (
	"fmt"
	"os"

	"github.com/zuens2020/mcp-relay/agent/internal/fsutil"
	"github.com/zuens2020/mcp-relay/agent/internal/paths"
	"gopkg.in/yaml.v3"
)

type HermesAdapter struct{}

func (HermesAdapter) Name() string { return "hermes" }

func (a HermesAdapter) Apply(r *paths.Resolver, servers map[string]ServerConfig) error {
	path, err := r.MCPPath("hermes")
	if err != nil {
		return err
	}
	doc := map[string]any{}
	if b, err := os.ReadFile(path); err == nil {
		if err := yaml.Unmarshal(b, &doc); err != nil {
			return fmt.Errorf("parse hermes config: %w", err)
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	if doc == nil {
		doc = map[string]any{}
	}
	managed, err := loadManaged(r, "hermes")
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
		mcp[id] = map[string]any(cfg)
		ids = append(ids, id)
	}
	doc["mcp_servers"] = mcp
	out, err := yaml.Marshal(doc)
	if err != nil {
		return err
	}
	if err := fsutil.AtomicWrite(r, path, out); err != nil {
		return err
	}
	return saveManaged(r, "hermes", ids)
}

func (a HermesAdapter) Diff(r *paths.Resolver, servers map[string]ServerConfig) (string, error) {
	path, _ := r.MCPPath("hermes")
	return fmt.Sprintf("path=%s incoming_servers=%d", path, len(servers)), nil
}
