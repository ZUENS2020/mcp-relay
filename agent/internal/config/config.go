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
	return &c, nil
}

func Save(path string, c *Config) error {
	b, err := yaml.Marshal(c)
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o600)
}
