"""Health and security checks for a running line-bridge install.

Prints one line per check and exits non-zero if any check fails.
Never prints secret values.
Usage: verify.py [--data-dir DIR]
"""

import argparse
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import httpx
import yaml

SYNAPSE_PORT = 18408
BRIDGE_PORT = 18722
results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((ok, name, detail))


def listening_addresses(port: int) -> list[str]:
    out = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True
    ).stdout.splitlines()[1:]
    return sorted({line.split()[8].rsplit(":", 1)[0] for line in out if len(line.split()) > 8})


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(Path.home() / ".local/share/line-bridge"))
    data = Path(ap.parse_args().data_dir)
    creds = json.loads((data / "credentials.json").read_text())
    hs = f"http://127.0.0.1:{SYNAPSE_PORT}"
    prov = f"http://127.0.0.1:{BRIDGE_PORT}/_matrix/provision/v3"
    auth = {"Authorization": f"Bearer {creds['access_token']}"}

    # --- network exposure ------------------------------------------------
    for port in (SYNAPSE_PORT, BRIDGE_PORT):
        addrs = listening_addresses(port)
        check(f"port {port} listens on loopback only", addrs == ["127.0.0.1"], ", ".join(addrs) or "not listening")

    hs_yaml = yaml.safe_load((data / "synapse" / "homeserver.yaml").read_text())
    check("federation disabled", hs_yaml.get("federation_domain_whitelist") == [] and not hs_yaml.get("trusted_key_servers"))
    check("open registration disabled", hs_yaml.get("enable_registration") is False)

    # --- authentication ---------------------------------------------------
    r = httpx.get(f"{prov}/whoami", params={"user_id": creds["user_id"]})
    check("provisioning rejects requests without a token", r.status_code in (401, 403), str(r.status_code))
    r = httpx.get(f"{prov}/whoami", params={"user_id": creds["user_id"]}, headers={"Authorization": "Bearer wrong"})
    check("provisioning rejects a wrong token", r.status_code in (401, 403), str(r.status_code))
    r = httpx.post(f"{hs}/_matrix/client/v3/register", json={"username": "probe", "password": "x" * 20, "auth": {"type": "m.login.dummy"}})
    check("client registration is closed", r.status_code in (400, 401, 403), str(r.status_code))
    nonce = httpx.get(f"{hs}/_synapse/admin/v1/register").json().get("nonce")
    r = httpx.post(f"{hs}/_synapse/admin/v1/register", json={"nonce": nonce, "username": "probe", "password": "x" * 20, "mac": "0" * 40})
    check("shared-secret registration rejects a bad MAC", r.status_code in (400, 403), str(r.status_code))
    r = httpx.get(f"{hs}/_matrix/client/v3/joined_rooms")
    check("client API requires a token", r.status_code == 401, str(r.status_code))

    bridge_cfg = yaml.safe_load((data / "bridge" / "config.yaml").read_text())
    perms = bridge_cfg["bridge"]["permissions"]
    check("only the owner has bridge permissions", perms == {creds["user_id"]: "admin"}, json.dumps(perms))
    reg = yaml.safe_load((data / "bridge" / "registration.yaml").read_text())
    check("appservice namespaces are exclusive to the bridge", all(ns.get("exclusive") for ns in reg["namespaces"]["users"]))

    # --- data at rest -------------------------------------------------------
    check("data dir is 700", mode(data) == 0o700, oct(mode(data)))
    loose = [
        str(p.relative_to(data))
        for p in data.rglob("*")
        if "venv" not in p.parts and mode(p) & 0o077
    ]
    check("nothing under the data dir is readable by others", not loose, ", ".join(loose[:5]))
    db = sqlite3.connect(f"file:{data / 'bridge' / 'bridge.db'}?mode=ro", uri=True)
    rows = db.execute("select metadata from user_login").fetchall()
    stored = [bool(json.loads(m or "{}").get("password")) for (m,) in rows]
    check("LINE password is not stored", rows and not any(stored), f"{len(rows)} login(s)")
    fv = subprocess.run(["fdesetup", "status"], capture_output=True, text=True).stdout.strip()
    check("FileVault is on", "FileVault is On" in fv, fv)

    # --- Claude Code guard ----------------------------------------------------
    settings = json.loads((Path.home() / ".claude" / "settings.json").read_text())
    ask = settings.get("permissions", {}).get("ask", [])
    check("Claude Code asks before every LINE send", "mcp__line__line_send_message" in ask)

    # --- health -----------------------------------------------------------------
    who = httpx.get(f"{prov}/whoami", params={"user_id": creds["user_id"]}, headers=auth).json()
    states = [(l.get("state") or {}).get("state_event") for l in who.get("logins") or []]
    check("LINE login is connected", states == ["CONNECTED"], ", ".join(map(str, states)) or "no login")
    joined = httpx.get(f"{hs}/_matrix/client/v3/joined_rooms", headers=auth).json().get("joined_rooms", [])
    check("portal rooms are joined", len(joined) > 0, f"{len(joined)} rooms")

    width = max(len(n) for _, n, _ in results)
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = sum(1 for ok, _, _ in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
