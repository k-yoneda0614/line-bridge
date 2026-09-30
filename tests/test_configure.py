import stat
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import configure  # noqa: E402


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def generated_synapse() -> dict:
    return {
        "server_name": "line.local",
        "listeners": [{"bind_addresses": ["::1", "127.0.0.1"], "port": 8008, "resources": [{"names": ["client", "federation"]}]}],
        "trusted_key_servers": [{"server_name": "matrix.org"}],
        "registration_shared_secret": "s",
    }


def generated_bridge() -> dict:
    return {
        "network": None,
        "bridge": {"permissions": {"*": "relay", "example.com": "user", "@admin:example.com": "admin"}},
        "database": {"type": "postgres", "uri": "postgres://"},
        "homeserver": {"address": "http://example.localhost:8008", "domain": "example.com"},
        "appservice": {"address": "http://localhost:29322", "public_address": "https://bridge.example.com", "hostname": "0.0.0.0", "port": 29322, "bot": {"username": "linebot", "avatar": None}},
        "matrix": {"federate_rooms": True},
        "backfill": {"enabled": False},
        "double_puppet": {"servers": {"x": "y"}, "secrets": {"x": "as_token:z"}},
        "encryption": {"allow": True},
        "logging": {"min_level": "debug"},
    }


def test_synapse_is_local_only(tmp_path):
    write(tmp_path / "synapse" / "homeserver.yaml", generated_synapse())
    configure.configure_synapse(tmp_path, 18408, "line.local")
    c = yaml.safe_load((tmp_path / "synapse" / "homeserver.yaml").read_text())

    assert c["listeners"] == [
        {
            "bind_addresses": ["127.0.0.1"],
            "port": 18408,
            "type": "http",
            "tls": False,
            "x_forwarded": False,
            "resources": [{"names": ["client"], "compress": False}],
        }
    ]
    assert c["trusted_key_servers"] == []
    assert c["federation_domain_whitelist"] == []
    assert c["enable_registration"] is False
    assert c["auto_accept_invites"]["only_from_local_users"] is True
    assert c["rc_joins"]["local"]["burst_count"] >= 1000
    assert stat.S_IMODE((tmp_path / "synapse" / "homeserver.yaml").stat().st_mode) == 0o600


def test_synapse_config_has_no_yaml_anchors(tmp_path):
    write(tmp_path / "synapse" / "homeserver.yaml", generated_synapse())
    configure.configure_synapse(tmp_path, 18408, "line.local")
    assert "&id" not in (tmp_path / "synapse" / "homeserver.yaml").read_text()


def test_bridge_permissions_and_binding(tmp_path):
    write(tmp_path / "bridge" / "config.yaml", generated_bridge())
    configure.configure_bridge(tmp_path, 18408, 18722, "line.local", "me")
    c = yaml.safe_load((tmp_path / "bridge" / "config.yaml").read_text())

    assert c["bridge"]["permissions"] == {"@me:line.local": "admin"}
    assert c["appservice"]["hostname"] == "127.0.0.1"
    assert c["appservice"]["public_address"] is None
    assert c["appservice"]["bot"]["avatar"] == ""
    assert c["homeserver"] == {"address": "http://127.0.0.1:18408", "domain": "line.local"}
    assert c["database"]["type"] == "sqlite3-fk-wal"
    assert c["double_puppet"]["secrets"] == {}
    assert c["encryption"]["allow"] is False
    assert c["matrix"]["federate_rooms"] is False
    assert c["logging"]["min_level"] == "info"


def test_configure_is_idempotent(tmp_path):
    write(tmp_path / "synapse" / "homeserver.yaml", generated_synapse())
    write(tmp_path / "bridge" / "config.yaml", generated_bridge())
    for _ in range(2):
        configure.configure_synapse(tmp_path, 18408, "line.local")
        configure.configure_bridge(tmp_path, 18408, 18722, "line.local", "me")
    first = [(tmp_path / p).read_text() for p in ("synapse/homeserver.yaml", "bridge/config.yaml")]
    configure.configure_synapse(tmp_path, 18408, "line.local")
    configure.configure_bridge(tmp_path, 18408, 18722, "line.local", "me")
    assert first == [(tmp_path / p).read_text() for p in ("synapse/homeserver.yaml", "bridge/config.yaml")]
