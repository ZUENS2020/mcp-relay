package wsclient

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/gorilla/websocket"
	syncer "github.com/zuens2020/mcp-relay/agent/internal/sync"
)

// Run maintains a WebSocket to the relay server and applies push messages.
func Run(c *syncer.Client) error {
	if c.Cfg.DeviceToken == "" {
		return fmt.Errorf("not registered")
	}
	base := strings.TrimRight(c.Cfg.RelayURL, "/")
	u, err := url.Parse(base)
	if err != nil {
		return err
	}
	switch u.Scheme {
	case "https":
		u.Scheme = "wss"
	case "http":
		u.Scheme = "ws"
	default:
		return fmt.Errorf("unsupported relay url scheme: %s", u.Scheme)
	}
	u.Path = strings.TrimRight(u.Path, "/") + "/api/v1/devices/ws"
	q := u.Query()
	q.Set("token", c.Cfg.DeviceToken)
	u.RawQuery = q.Encode()

	dialer := websocket.Dialer{HandshakeTimeout: 15 * time.Second}
	header := http.Header{}
	header.Set("Authorization", "Bearer "+c.Cfg.DeviceToken)
	conn, _, err := dialer.Dial(u.String(), header)
	if err != nil {
		return err
	}
	defer conn.Close()

	_ = conn.SetReadDeadline(time.Time{})
	for {
		_, raw, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		var msg map[string]any
		if err := json.Unmarshal(raw, &msg); err != nil {
			continue
		}
		typ, _ := msg["type"].(string)
		switch typ {
		case "connected", "pong", "push.ack.received":
			continue
		case "push.apply":
			deliveryID, _ := msg["delivery_id"].(string)
			releaseID, _ := msg["release_id"].(string)
			targets := parseTargets(msg["targets"])
			applyErr := c.ApplyRelease(releaseID, targets, "")
			ack := map[string]any{
				"type":        "push.ack",
				"delivery_id": deliveryID,
				"ok":          applyErr == nil,
			}
			if applyErr != nil {
				ack["detail"] = map[string]any{"error": applyErr.Error()}
			}
			_ = conn.WriteJSON(ack)
		case "ping":
			_ = conn.WriteJSON(map[string]string{"type": "pong"})
		default:
			continue
		}
	}
}

func parseTargets(v any) []string {
	arr, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(arr))
	for _, x := range arr {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}
