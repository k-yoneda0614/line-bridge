"""Apply the local-only settings to the generated Synapse and bridge configs.

Idempotent: safe to run after every config regeneration.
Usage: configure.py synapse|bridge <data_dir> <synapse_port> <bridge_port> <server_name> <matrix_user>
"""

import sys
from pathlib import Path

import yaml


def configure_synapse(data: Path, synapse_port: int, server_name: str) -> None:
    path = data / "synapse" / "homeserver.yaml"
    c = yaml.safe_load(path.read_text())
    c["server_name"] = server_name
    c["listeners"] = [
        {
            "bind_addresses": ["127.0.0.1"],
            "port": synapse_port,
            "type": "http",
            "tls": False,
            "x_forwarded": False,
            "resources": [{"names": ["client"], "compress": False}],
        }
    ]
    # No federation: this homeserver only talks to the local bridge.
    c["trusted_key_servers"] = []
    c["federation_domain_whitelist"] = []
    c["enable_registration"] = False
    c["report_stats"] = False
    c["presence"] = {"enabled": False}
    c["max_upload_size"] = "100M"
    c["app_service_config_files"] = [str(data / "bridge" / "registration.yaml")]
    # Single-user homeserver: the default join/invite ratelimits (~0.1 joins/s)
    # make auto-accept give up after 5 retries when the first sync creates
    # hundreds of portal rooms at once.
    fast = {"per_second": 100, "burst_count": 1000}
    c["rc_joins"] = {"local": dict(fast), "remote": {"per_second": 0.01, "burst_count": 10}}
    c["rc_joins_per_room"] = dict(fast)
    c["rc_invites"] = {"per_room": dict(fast), "per_user": dict(fast), "per_issuer": dict(fast)}
    c["rc_message"] = dict(fast)
    # The bridge invites us to every portal room; accept without a Matrix client.
    c["auto_accept_invites"] = {
        "enabled": True,
        "only_for_direct_messages": False,
        "only_from_local_users": True,
    }
    path.write_text(yaml.safe_dump(c, sort_keys=False, allow_unicode=True))
    path.chmod(0o600)


def configure_bridge(data: Path, synapse_port: int, bridge_port: int, server_name: str, user: str) -> None:
    path = data / "bridge" / "config.yaml"
    c = yaml.safe_load(path.read_text())
    c["network"] = c.get("network") or {}
    c["bridge"]["permissions"] = {f"@{user}:{server_name}": "admin"}
    c["database"] = {
        "type": "sqlite3-fk-wal",
        "uri": f"file:{data}/bridge/bridge.db?_txlock=immediate",
        "max_open_conns": 5,
        "max_idle_conns": 1,
        "max_conn_idle_time": None,
        "max_conn_lifetime": None,
    }
    c["homeserver"].update({"address": f"http://127.0.0.1:{synapse_port}", "domain": server_name})
    c["appservice"].update(
        {
            "address": f"http://127.0.0.1:{bridge_port}",
            "public_address": None,
            "hostname": "127.0.0.1",
            "port": bridge_port,
        }
    )
    # PyYAML turns the generated empty `avatar:` into null, which the bridge warns about.
    if c["appservice"]["bot"].get("avatar") is None:
        c["appservice"]["bot"]["avatar"] = ""
    c["matrix"]["federate_rooms"] = False
    c["backfill"]["enabled"] = True
    c["double_puppet"] = {"servers": {}, "allow_discovery": False, "secrets": {}}
    c["encryption"]["allow"] = False
    c["logging"] = {
        "min_level": "info",
        "writers": [
            {
                "type": "file",
                "format": "json",
                "filename": str(data / "logs" / "bridge.log"),
                "max_size": 50,
                "max_backups": 5,
                "compress": False,
            }
        ],
    }
    path.write_text(yaml.safe_dump(c, sort_keys=False, allow_unicode=True))
    path.chmod(0o600)


def main() -> None:
    target, data, synapse_port, bridge_port, server_name, user = sys.argv[1:7]
    data_dir = Path(data)
    if target == "synapse":
        configure_synapse(data_dir, int(synapse_port), server_name)
    elif target == "bridge":
        configure_bridge(data_dir, int(synapse_port), int(bridge_port), server_name, user)
    else:
        sys.exit(f"unknown target: {target}")


if __name__ == "__main__":
    main()
