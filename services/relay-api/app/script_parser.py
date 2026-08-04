"""Relay batch configuration script parser.

Supports YAML documents and a compact line DSL.

YAML example
------------
version: 1
ops:
  - match:
      profile: windows-desktop
    agents:
      cursor:
        enable: [trek, nowledge-mem, drawio]
        disable: [jeb]
      pi:
        enabled: true
        enable: [trek]
  - match:
      device_id: nec-server-07538527cbf9
    agents:
      hermes:
        enable_all: true

Line DSL example
----------------
# comments allowed
enable profile:windows-desktop agent:cursor trek nowledge-mem drawio
disable profile:windows-desktop agent:cursor jeb
enable device:nec-server-xxx agent:hermes trek
set device:nec-server-xxx agents=cursor,hermes
enable_all profile:nec-server agent:hermes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

TARGETS = ("cursor", "hermes", "pi", "codex", "claude-code")
PROFILES = ("windows-desktop", "mac-laptop", "nec-server")


@dataclass
class Match:
    profile: str | None = None
    device_id: str | None = None
    hostname_contains: str | None = None

    def matches(self, device: dict[str, Any]) -> bool:
        if self.profile and device.get("profile") != self.profile:
            return False
        if self.device_id and device.get("device_id") != self.device_id:
            return False
        if self.hostname_contains:
            host = (device.get("hostname") or "").lower()
            if self.hostname_contains.lower() not in host:
                return False
        return True


@dataclass
class AgentSpec:
    enabled: bool | None = None
    enable: list[str] = field(default_factory=list)
    disable: list[str] = field(default_factory=list)
    enable_all: bool = False
    disable_all: bool = False


@dataclass
class Op:
    match: Match
    agents: dict[str, AgentSpec] = field(default_factory=dict)
    set_agents: list[str] | None = None  # replace detected/enabled agent list


@dataclass
class Script:
    version: int
    ops: list[Op]
    source: str = "yaml"


@dataclass
class ParseError:
    line: int | None
    message: str


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x) for x in v]
    raise ValueError(f"expected list/str, got {type(v)}")


def _parse_agent_spec(raw: dict[str, Any]) -> AgentSpec:
    return AgentSpec(
        enabled=raw.get("enabled"),
        enable=_as_list(raw.get("enable")),
        disable=_as_list(raw.get("disable")),
        enable_all=bool(raw.get("enable_all", False)),
        disable_all=bool(raw.get("disable_all", False)),
    )


def parse_yaml(text: str) -> tuple[Script | None, list[ParseError]]:
    errors: list[ParseError] = []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return None, [ParseError(None, f"yaml error: {e}")]
    if not isinstance(data, dict):
        return None, [ParseError(None, "root must be a mapping")]
    version = int(data.get("version") or 1)
    if version != 1:
        errors.append(ParseError(None, f"unsupported version {version}"))
    ops_raw = data.get("ops") or []
    if not isinstance(ops_raw, list):
        return None, [ParseError(None, "ops must be a list")]
    ops: list[Op] = []
    for i, item in enumerate(ops_raw):
        if not isinstance(item, dict):
            errors.append(ParseError(None, f"ops[{i}] must be mapping"))
            continue
        m = item.get("match") or {}
        if not isinstance(m, dict):
            errors.append(ParseError(None, f"ops[{i}].match must be mapping"))
            continue
        match = Match(
            profile=m.get("profile"),
            device_id=m.get("device_id"),
            hostname_contains=m.get("hostname_contains") or m.get("hostname"),
        )
        if match.profile and match.profile not in PROFILES:
            errors.append(ParseError(None, f"ops[{i}] invalid profile {match.profile}"))
        agents: dict[str, AgentSpec] = {}
        for agent, spec in (item.get("agents") or {}).items():
            if agent not in TARGETS:
                errors.append(ParseError(None, f"ops[{i}] unknown agent {agent}"))
                continue
            if not isinstance(spec, dict):
                errors.append(ParseError(None, f"ops[{i}].agents.{agent} must be mapping"))
                continue
            agents[agent] = _parse_agent_spec(spec)
        set_agents = None
        if "set_agents" in item:
            set_agents = _as_list(item.get("set_agents"))
            for a in set_agents:
                if a not in TARGETS:
                    errors.append(ParseError(None, f"ops[{i}] invalid set_agents entry {a}"))
        ops.append(Op(match=match, agents=agents, set_agents=set_agents))
    if errors:
        return None, errors
    return Script(version=version, ops=ops, source="yaml"), []


def parse_dsl(text: str) -> tuple[Script | None, list[ParseError]]:
    """Compact line DSL → Script."""
    errors: list[ParseError] = []
    ops: list[Op] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        cmd = parts[0].lower()
        try:
            if cmd == "enable" or cmd == "disable" or cmd == "enable_all" or cmd == "disable_all":
                # enable profile:X agent:Y a b c
                # enable device:ID agent:Y a b c
                match = Match()
                agent = None
                servers: list[str] = []
                for tok in parts[1:]:
                    if tok.startswith("profile:"):
                        match.profile = tok.split(":", 1)[1]
                    elif tok.startswith("device:"):
                        match.device_id = tok.split(":", 1)[1]
                    elif tok.startswith("agent:"):
                        agent = tok.split(":", 1)[1]
                    elif tok.startswith("host:"):
                        match.hostname_contains = tok.split(":", 1)[1]
                    else:
                        servers.append(tok)
                if not agent:
                    raise ValueError("missing agent:")
                if agent not in TARGETS:
                    raise ValueError(f"unknown agent {agent}")
                if match.profile and match.profile not in PROFILES:
                    raise ValueError(f"invalid profile {match.profile}")
                if not match.profile and not match.device_id and not match.hostname_contains:
                    raise ValueError("need profile: / device: / host:")
                spec = AgentSpec()
                if cmd == "enable":
                    spec.enable = servers
                elif cmd == "disable":
                    spec.disable = servers
                elif cmd == "enable_all":
                    spec.enable_all = True
                elif cmd == "disable_all":
                    spec.disable_all = True
                ops.append(Op(match=match, agents={agent: spec}))
            elif cmd == "set":
                # set device:ID agents=cursor,hermes
                # set profile:X agents=cursor,pi
                match = Match()
                agents_list: list[str] = []
                for tok in parts[1:]:
                    if tok.startswith("profile:"):
                        match.profile = tok.split(":", 1)[1]
                    elif tok.startswith("device:"):
                        match.device_id = tok.split(":", 1)[1]
                    elif tok.startswith("host:"):
                        match.hostname_contains = tok.split(":", 1)[1]
                    elif tok.startswith("agents="):
                        agents_list = [x for x in tok.split("=", 1)[1].split(",") if x]
                    else:
                        raise ValueError(f"unknown token {tok}")
                if not agents_list:
                    raise ValueError("missing agents=")
                for a in agents_list:
                    if a not in TARGETS:
                        raise ValueError(f"invalid agent {a}")
                ops.append(Op(match=match, set_agents=agents_list))
            else:
                raise ValueError(f"unknown command {cmd}")
        except ValueError as e:
            errors.append(ParseError(lineno, str(e)))
    if errors:
        return None, errors
    return Script(version=1, ops=ops, source="dsl"), []


def parse_script(text: str, fmt: str | None = None) -> tuple[Script | None, list[ParseError]]:
    text = text.strip()
    if not text:
        return None, [ParseError(None, "empty script")]
    if fmt == "dsl":
        return parse_dsl(text)
    if fmt == "yaml":
        return parse_yaml(text)
    # auto-detect
    if text.startswith("version:") or text.startswith("ops:") or text.lstrip().startswith("{"):
        return parse_yaml(text)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")), "")
    if first.split()[0].lower() in {"enable", "disable", "enable_all", "disable_all", "set"}:
        return parse_dsl(text)
    return parse_yaml(text)


def apply_script_to_device_config(
    device: dict[str, Any],
    agent_config: dict[str, Any],
    script: Script,
    known_servers: list[str],
) -> tuple[dict[str, Any], list[str], bool]:
    """Return (new_agent_config, new_targets_list, changed).

    agent_config shape:
      {
        "cursor": {
          "enabled": true,
          "servers": {"trek": true, "drawio": false}  # missing = inherit binding default
        }
      }
    """
    cfg = {k: dict(v) if isinstance(v, dict) else v for k, v in (agent_config or {}).items()}
    targets = list(device.get("targets") or [])
    changed = False
    for op in script.ops:
        if not op.match.matches(device):
            continue
        if op.set_agents is not None:
            targets = list(op.set_agents)
            for a in targets:
                cfg.setdefault(a, {"enabled": True, "servers": {}})
            changed = True
        for agent, spec in op.agents.items():
            entry = dict(cfg.get(agent) or {"enabled": True, "servers": {}})
            servers = dict(entry.get("servers") or {})
            if spec.enabled is not None:
                entry["enabled"] = bool(spec.enabled)
                changed = True
            if spec.enable_all:
                for sid in known_servers:
                    servers[sid] = True
                changed = True
            if spec.disable_all:
                for sid in known_servers:
                    servers[sid] = False
                changed = True
            for sid in spec.enable:
                servers[sid] = True
                changed = True
            for sid in spec.disable:
                servers[sid] = False
                changed = True
            entry["servers"] = servers
            # flag-based script edits supersede a previously pinned document
            entry.pop("mcp_servers", None)
            cfg[agent] = entry
            if agent not in targets and entry.get("enabled", True):
                targets.append(agent)
                changed = True
    return cfg, targets, changed
