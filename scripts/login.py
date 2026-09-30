"""Log the bridge in to LINE. Run this yourself in a terminal.

The password is read with getpass and sent only to the local bridge
(127.0.0.1). Nothing is printed or logged by this script.
Usage: login.py [--data-dir DIR] [--bridge-port PORT]
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

import httpx

FLOW_ID = "dev.highest.matrix.line.email_login"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(Path.home() / ".local/share/line-bridge"))
    ap.add_argument("--bridge-port", type=int, default=18722)
    args = ap.parse_args()

    creds = json.loads((Path(args.data_dir) / "credentials.json").read_text())
    base = f"http://127.0.0.1:{args.bridge_port}/_matrix/provision/v3"
    params = {"user_id": creds["user_id"]}
    headers = {"Authorization": f"Bearer {creds['access_token']}"}
    # display_and_wait blocks until the PIN is confirmed on the phone.
    client = httpx.Client(base_url=base, params=params, headers=headers, timeout=httpx.Timeout(10, read=600))

    existing = client.get("/logins").json().get("login_ids") or []
    if existing:
        print(f"Already logged in: {', '.join(existing)}")
        if input("Log in again? [y/N] ").strip().lower() != "y":
            return

    print("Log out of the LINE Chrome extension and any other bridge on this account first.")
    print("This bridge logs in as the Chrome extension client; two such sessions keep kicking each other out.\n")

    step = client.post(f"/login/start/{FLOW_ID}", json={}).raise_for_status().json()
    login_id = step["login_id"]

    while True:
        kind = step["type"]
        if step.get("instructions"):
            print(f"\n{step['instructions']}\n")

        if kind == "complete":
            print("Logged in. Chats will start syncing.")
            return

        if kind == "user_input":
            data = {}
            for field in step["user_input"]["fields"]:
                label = field.get("name") or field["id"]
                if field.get("type") == "password":
                    data[field["id"]] = getpass.getpass(f"{label}: ")
                else:
                    data[field["id"]] = input(f"{label}: ").strip()
            r = client.post(f"/login/step/{login_id}/{step['step_id']}/user_input", json=data)
        elif kind == "display_and_wait":
            print("Confirm on your phone's LINE app. Waiting...")
            r = client.post(f"/login/step/{login_id}/{step['step_id']}/display_and_wait", json={})
        else:
            client.post(f"/login/cancel/{login_id}", json={})
            sys.exit(f"Unsupported login step: {kind}")

        if r.status_code >= 400:
            try:
                err = r.json().get("error", r.text)
            except ValueError:
                err = r.text
            client.post(f"/login/cancel/{login_id}", json={})
            sys.exit(f"Login failed: {err}")
        step = r.json()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted")
