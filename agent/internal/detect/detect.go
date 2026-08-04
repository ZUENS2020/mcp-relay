package detect

import (
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/zuens2020/mcp-relay/agent/internal/paths"
)

type Result struct {
	Profile string   `json:"profile"`
	Targets []string `json:"targets"`
	Notes   []string `json:"notes,omitempty"`
}

func Profile(home string) string {
	if forced := os.Getenv("RELAY_PROFILE"); forced != "" {
		return forced
	}
	host, _ := os.Hostname()
	host = strings.ToLower(host)
	if host == "nec" || strings.Contains(host, "nec") {
		return "nec-server"
	}
	if hasLocalIP("127.0.0.1") {
		return "nec-server"
	}
	switch runtime.GOOS {
	case "windows":
		return "windows-desktop"
	case "darwin":
		return "mac-laptop"
	default:
		return "nec-server"
	}
}

func hasLocalIP(want string) bool {
	ifaces, err := net.Interfaces()
	if err != nil {
		return false
	}
	for _, iface := range ifaces {
		addrs, _ := iface.Addrs()
		for _, a := range addrs {
			var ip net.IP
			switch v := a.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}
			if ip != nil && ip.String() == want {
				return true
			}
		}
	}
	return false
}

func inPATH(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

func Targets(r *paths.Resolver) ([]string, []string) {
	home := r.Home()
	usePATH := r.Mode != paths.ModeSandbox // sandbox: only fake home tree
	var found []string
	var notes []string

	if exists(filepath.Join(home, ".cursor")) || exists(filepath.Join(home, ".cursor", "mcp.json")) || (usePATH && inPATH("cursor")) {
		found = append(found, "cursor")
	}
	hermesHome := os.Getenv("HERMES_HOME")
	if hermesHome == "" || r.Mode == paths.ModeSandbox {
		hermesHome = filepath.Join(home, ".hermes")
	}
	if exists(filepath.Join(hermesHome, "config.yaml")) || exists(hermesHome) || exists(filepath.Join(hermesHome, "bin", "hermes")) || (usePATH && inPATH("hermes")) {
		found = append(found, "hermes")
	}
	piDir := os.Getenv("PI_CODING_AGENT_DIR")
	if piDir == "" || r.Mode == paths.ModeSandbox {
		piDir = filepath.Join(home, ".pi", "agent")
	}
	if exists(piDir) || (usePATH && inPATH("pi")) {
		found = append(found, "pi")
		ext := filepath.Join(piDir, "extensions")
		if exists(ext) {
			entries, _ := os.ReadDir(ext)
			hasAdapter := false
			for _, e := range entries {
				n := strings.ToLower(e.Name())
				if strings.Contains(n, "mcp") {
					hasAdapter = true
					break
				}
			}
			if !hasAdapter {
				notes = append(notes, "pi: mcp.json will be written; install pi-mcp-adapter to load MCP")
			}
		} else {
			notes = append(notes, "pi: mcp.json will be written; install pi-mcp-adapter to load MCP")
		}
	}
	if exists(filepath.Join(home, ".codex", "config.toml")) || exists(filepath.Join(home, ".codex")) || (usePATH && inPATH("codex")) {
		found = append(found, "codex")
	}
	// Claude Code: ~/.claude.json or ~/.claude/ or claude binary.
	// Do NOT treat Claude Desktop (%APPDATA%/Claude) as claude-code.
	if exists(filepath.Join(home, ".claude.json")) || exists(filepath.Join(home, ".claude")) || (usePATH && inPATH("claude")) {
		found = append(found, "claude-code")
	}

	return found, notes
}

func Run(r *paths.Resolver) Result {
	t, notes := Targets(r)
	return Result{Profile: Profile(r.RealHome), Targets: t, Notes: notes}
}
