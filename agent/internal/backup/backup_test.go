package backup

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/zuens2020/mcp-relay/agent/internal/paths"
)

func TestBackupCopiesMCPFiles(t *testing.T) {
	home := t.TempDir()
	relay := filepath.Join(home, ".mcp-relay")
	cursorDir := filepath.Join(home, ".cursor")
	if err := os.MkdirAll(cursorDir, 0o755); err != nil {
		t.Fatal(err)
	}
	mcp := filepath.Join(cursorDir, "mcp.json")
	if err := os.WriteFile(mcp, []byte(`{"mcpServers":{"trek":{"url":"https://x"}}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	res := &paths.Resolver{Mode: paths.ModeLive, RealHome: home, RelayRoot: relay, SandboxRoot: filepath.Join(relay, "sandbox")}
	dir, err := Run(res, []string{"cursor"})
	if err != nil {
		t.Fatal(err)
	}
	bak := filepath.Join(dir, "cursor-mcp.json")
	b, err := os.ReadFile(bak)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) == "" || !contains(string(b), "trek") {
		t.Fatalf("unexpected backup content: %s", b)
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || len(sub) == 0 || (len(s) > 0 && (func() bool {
		for i := 0; i+len(sub) <= len(s); i++ {
			if s[i:i+len(sub)] == sub {
				return true
			}
		}
		return false
	})()))
}
