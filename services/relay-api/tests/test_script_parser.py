"""Tests for batch configuration script parser."""

from app.script_parser import apply_script_to_device_config, parse_script


def test_parse_dsl_enable():
    script, errs = parse_script(
        "enable profile:windows-desktop agent:cursor trek nowledge-mem\n"
        "disable profile:windows-desktop agent:cursor jeb\n",
        "dsl",
    )
    assert not errs
    assert script is not None
    assert len(script.ops) == 2
    assert script.ops[0].agents["cursor"].enable == ["trek", "nowledge-mem"]
    assert script.ops[1].agents["cursor"].disable == ["jeb"]


def test_parse_yaml_and_apply():
    text = """
version: 1
ops:
  - match:
      profile: nec-server
    agents:
      hermes:
        enable_all: true
      cursor:
        disable: [jeb]
"""
    script, errs = parse_script(text, "yaml")
    assert not errs
    device = {"device_id": "d1", "profile": "nec-server", "hostname": "nec", "targets": ["hermes", "cursor"]}
    known = ["trek", "jeb", "nowledge-mem"]
    cfg, targets, changed = apply_script_to_device_config(device, {}, script, known)
    assert changed
    assert cfg["hermes"]["servers"]["trek"] is True
    assert cfg["cursor"]["servers"]["jeb"] is False
    assert "hermes" in targets


def test_set_agents_dsl():
    script, errs = parse_script("set device:abc agents=cursor,pi", "dsl")
    assert not errs
    device = {"device_id": "abc", "profile": "windows-desktop", "targets": ["cursor"]}
    cfg, targets, changed = apply_script_to_device_config(device, {}, script, ["trek"])
    assert changed
    assert targets == ["cursor", "pi"]
