package syncer

import (
	"fmt"

	"github.com/zuens2020/mcp-relay/agent/internal/adapters"
)

type bootstrapResp struct {
	Status      string   `json:"status"`
	Reason      string   `json:"reason"`
	ServerCount int      `json:"server_count"`
	Servers     []string `json:"servers"`
}

// BootstrapTarget uploads local mcpServers when the server has none for this agent.
func (c *Client) BootstrapTarget(target string) (*bootstrapResp, error) {
	servers, err := adapters.ReadLocalMCPServers(c.Res, target)
	if err != nil {
		return nil, err
	}
	if len(servers) == 0 {
		return &bootstrapResp{Status: "skipped", Reason: "local_empty"}, nil
	}
	body := map[string]any{
		"mcp_document": map[string]any{
			"mcpServers": servers,
		},
	}
	var out bootstrapResp
	path := fmt.Sprintf("/api/v1/devices/me/agents/%s/bootstrap", target)
	if err := c.postJSON(path, body, map[string]string{
		"Authorization": "Bearer " + c.Cfg.DeviceToken,
	}, &out); err != nil {
		return nil, err
	}
	return &out, nil
}
