"""Create the local Matrix user and save its access token to credentials.json.

Uses Synapse's shared-secret registration, so no interactive prompt is needed.
The Matrix password is random and local-only; it is not the LINE password.
Usage: create_user.py <data_dir> <synapse_port> <server_name> <matrix_user>
"""

import hashlib
import hmac
import json
import secrets
import sys
from pathlib import Path

import httpx
import yaml


def main() -> None:
    data, port, server_name, user = sys.argv[1:5]
    data_dir = Path(data)
    creds_path = data_dir / "credentials.json"
    base = f"http://127.0.0.1:{port}"

    if creds_path.exists():
        creds = json.loads(creds_path.read_text())
        r = httpx.get(
            f"{base}/_matrix/client/v3/account/whoami",
            headers={"Authorization": f"Bearer {creds['access_token']}"},
        )
        if r.status_code == 200:
            print(f"already registered: {creds['user_id']}")
            return
        sys.exit(f"credentials.json exists but the token is rejected ({r.status_code}); remove it to re-register")

    hs = yaml.safe_load((data_dir / "synapse" / "homeserver.yaml").read_text())
    shared_secret = hs["registration_shared_secret"]
    password = secrets.token_urlsafe(32)

    nonce = httpx.get(f"{base}/_synapse/admin/v1/register").json()["nonce"]
    mac = hmac.new(shared_secret.encode(), digestmod=hashlib.sha1)
    mac.update(b"\x00".join([nonce.encode(), user.encode(), password.encode(), b"notadmin"]))
    r = httpx.post(
        f"{base}/_synapse/admin/v1/register",
        json={"nonce": nonce, "username": user, "password": password, "admin": False, "mac": mac.hexdigest()},
    )
    r.raise_for_status()
    body = r.json()

    creds = {
        "homeserver": base,
        "user_id": body["user_id"],
        "access_token": body["access_token"],
        "device_id": body.get("device_id"),
        "password": password,
    }
    creds_path.write_text(json.dumps(creds, indent=2))
    creds_path.chmod(0o600)
    print(f"registered: {body['user_id']}")


if __name__ == "__main__":
    main()
