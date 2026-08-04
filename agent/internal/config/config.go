package config

import (
	"os"

	"gopkg.in/yaml.v3"
)

type Config struct {
	RelayURL         string   `yaml:"relay_url"`
	DeviceID         string   `yaml:"device_id"`
	DeviceToken      string   `yaml:"device_token"`
	Profile          string   `yaml:"profile"`
	Targets          []string `yaml:"targets"`
	AllowLiveWrites  bool     `yaml:"allow_live_writes"`
	AgentVersion     string   `yaml:"agent_version"`
	// Cloudflare Access Service Token (machine identity at the edge).
	// Read from env at load time; never persisted by Save().
	CFAccessClientID     string `yaml:"-"`
	CFAccessClientSecret string `yaml:"-"`
}

// CloudflareAccessHeaders returns the CF-Access-* headers if a service token
// is configured, nil otherwise. Used by HTTP and WebSocket calls so the agent
// can pass through a Cloudflare Access policy that requires Service Auth.
func (c *Config) CloudflareAccessHeaders() map[string]string {
	if c.CFAccessClientID == "" || c.CFAccessClientSecret == "" {
		return nil
	}
	return map[string]string{
		"CF-Access-Client-Id":     c.CFAccessClientID,
		"CF-Access-Client-Secret": c.CFAccessClientSecret,
	}
}

func Load(path string) (*Config, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return &Config{
				RelayURL:        "http://127.0.0.1:8740",
				AgentVersion:    "0.1.0",
				AllowLiveWrites: true,
			}, nil
		}
		return nil, err
	}
	var c Config
	if err := yaml.Unmarshal(b, &c); err != nil {
		return nil, err
	}
	if c.RelayURL == "" {
		c.RelayURL = "http://127.0.0.1:8740"
	}
	if c.AgentVersion == "" {
		c.AgentVersion = "0.1.0"
	}
	// Cloudflare Access service token comes from the environment so it never
	// lands in config.yaml (and survives `mcp-relay init` rewrites).
	c.CFAccessClientID = os.Getenv("CF_ACCESS_CLIENT_ID")
	c.CFAccessClientSecret = os.Getenv("CF_ACCESS_CLIENT_SECRET")
	return &c, nil
}

func Save(path string, c *Config) error {
	b, err := yaml.Marshal(c)
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o600)
}
