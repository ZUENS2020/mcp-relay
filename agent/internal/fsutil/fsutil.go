package fsutil

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/zuens2020/mcp-relay/agent/internal/paths"
)

func FileHash(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func AtomicWrite(r *paths.Resolver, path string, data []byte) error {
	if r.Mode == paths.ModeDryRun {
		fmt.Printf("would write %s (%d bytes)\n", path, len(data))
		return nil
	}
	if err := r.AssertWritable(path); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	if _, err := os.Stat(path); err == nil {
		bak := filepath.Join(r.BackupsDir(), filepath.Base(path)+"."+time.Now().Format("20060102-150405")+".relay.bak")
		if err := os.MkdirAll(r.BackupsDir(), 0o755); err != nil {
			return err
		}
		in, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if err := r.AssertWritable(bak); err != nil {
			return err
		}
		if err := os.WriteFile(bak, in, 0o600); err != nil {
			return err
		}
		_ = os.WriteFile(path+".relay.bak", in, 0o600)
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func CopyDir(src, dst string, r *paths.Resolver) error {
	if r.Mode == paths.ModeDryRun {
		fmt.Printf("would copy dir %s -> %s\n", src, dst)
		return nil
	}
	if err := r.AssertWritable(dst); err != nil {
		return err
	}
	return filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		return os.WriteFile(target, data, 0o644)
	})
}
