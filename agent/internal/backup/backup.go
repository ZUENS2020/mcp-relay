package backup

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/zuens2020/mcp-relay/agent/internal/detect"
	"github.com/zuens2020/mcp-relay/agent/internal/paths"
)

// Run copies existing MCP config files for detected targets into
// <backupsDir>/<timestamp>/ before any live writes.
func Run(res *paths.Resolver, targets []string) (string, error) {
	if len(targets) == 0 {
		det := detect.Run(res)
		targets = det.Targets
	}
	ts := time.Now().UTC().Format("20060102T150405Z")
	dir := filepath.Join(res.BackupsDir(), ts)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	copied := 0
	meta := ""
	for _, t := range targets {
		src, err := res.MCPPath(t)
		if err != nil {
			continue
		}
		if _, err := os.Stat(src); err != nil {
			continue
		}
		dst := filepath.Join(dir, t+filepath.Ext(src))
		if filepath.Ext(src) == "" {
			dst = filepath.Join(dir, t+".bak")
		}
		// preserve meaningful names
		switch t {
		case "cursor", "pi":
			dst = filepath.Join(dir, t+"-mcp.json")
		case "hermes":
			dst = filepath.Join(dir, "hermes-config.yaml")
		case "codex":
			dst = filepath.Join(dir, "codex-config.toml")
		case "claude-code":
			dst = filepath.Join(dir, "claude.json")
		}
		if err := copyFile(src, dst); err != nil {
			return "", fmt.Errorf("backup %s: %w", t, err)
		}
		copied++
		meta += fmt.Sprintf("%s <= %s\n", filepath.Base(dst), src)
	}
	_ = os.WriteFile(filepath.Join(dir, "MANIFEST.txt"), []byte(meta), 0o600)
	if copied == 0 {
		_ = os.WriteFile(filepath.Join(dir, "EMPTY"), []byte("no mcp files found to backup\n"), 0o600)
	}
	return dir, nil
}

func List(res *paths.Resolver) ([]string, error) {
	root := res.BackupsDir()
	entries, err := os.ReadDir(root)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var out []string
	for _, e := range entries {
		if e.IsDir() {
			out = append(out, filepath.Join(root, e.Name()))
		}
	}
	return out, nil
}

func Latest(res *paths.Resolver) (string, error) {
	list, err := List(res)
	if err != nil {
		return "", err
	}
	if len(list) == 0 {
		return "", fmt.Errorf("no backups under %s", res.BackupsDir())
	}
	// directory names are UTC timestamps → lexical max is latest
	best := list[0]
	for _, p := range list[1:] {
		if filepath.Base(p) > filepath.Base(best) {
			best = p
		}
	}
	return best, nil
}

// Restore copies files from a backup dir back to MCP paths (by known filenames).
func Restore(res *paths.Resolver, backupDir string) error {
	mapping := map[string]string{
		"cursor-mcp.json":    "cursor",
		"hermes-config.yaml": "hermes",
		"pi-mcp.json":        "pi",
		"codex-config.toml":  "codex",
		"claude.json":        "claude-code",
	}
	entries, err := os.ReadDir(backupDir)
	if err != nil {
		return err
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		target, ok := mapping[e.Name()]
		if !ok {
			continue
		}
		dst, err := res.MCPPath(target)
		if err != nil {
			return err
		}
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return err
		}
		if err := copyFile(filepath.Join(backupDir, e.Name()), dst); err != nil {
			return fmt.Errorf("restore %s: %w", target, err)
		}
	}
	return nil
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
