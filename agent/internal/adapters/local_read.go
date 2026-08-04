package adapters

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/pelletier/go-toml/v2"
	"github.com/zuens2020/mcp-relay/agent/internal/paths"
	"gopkg.in/yaml.v3"
)

// ReadLocalMCPServers returns the local mcpServers-equivalent map for a target.
func ReadLocalMCPServers(r *paths.Resolver, target string) (map[string]ServerConfig, error) {
	path, err := r.MCPPath(target)
	if err != nil {
		return nil, err
	}
	b, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return map[string]ServerConfig{}, nil
		}
		return nil, err
	}
	switch target {
	case "cursor", "pi", "claude-code":
		var doc map[string]any
		if err := json.Unmarshal(b, &doc); err != nil {
			return nil, err
		}
		return coerceServers(doc["mcpServers"]), nil
	case "hermes":
		var doc map[string]any
		if err := yaml.Unmarshal(b, &doc); err != nil {
			return nil, err
		}
		// hermes: mcp_servers: { name: { url, ... } }
		return coerceServers(doc["mcp_servers"]), nil
	case "codex":
		var doc map[string]any
		if err := toml.Unmarshal(b, &doc); err != nil {
			return nil, err
		}
		// [mcp_servers.name]
		raw, _ := doc["mcp_servers"].(map[string]any)
		return coerceServers(raw), nil
	default:
		return nil, fmt.Errorf("unknown target %s", target)
	}
}

func coerceServers(v any) map[string]ServerConfig {
	out := map[string]ServerConfig{}
	m, ok := v.(map[string]any)
	if !ok || m == nil {
		return out
	}
	for id, cfg := range m {
		id = strings.TrimSpace(id)
		if id == "" {
			continue
		}
		if cm, ok := cfg.(map[string]any); ok {
			out[id] = ServerConfig(cm)
		} else {
			out[id] = ServerConfig{}
		}
	}
	return out
}
