"""Command-line access to the same functions as the line MCP server.

For sessions where the MCP tools are not loaded. Output is JSON.
Sending requires --confirmed, to be passed only after the user approved the
exact text and chat. The Claude Code `ask` rule does not apply to this CLI.

Usage:
  line_cli.py status
  line_cli.py chats [--query Q] [--limit N]
  line_cli.py read CHAT_ID [--limit N] [--before CURSOR]
  line_cli.py search QUERY [--chat CHAT_ID] [--limit N]
  line_cli.py send CHAT_ID TEXT --confirmed [--reply-to MESSAGE_ID]
  line_cli.py media CHAT_ID MESSAGE_ID
  line_cli.py send-media CHAT_ID FILE_PATH --confirmed [--reply-to MESSAGE_ID]
  line_cli.py delivered MESSAGE_ID
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import line_mcp  # noqa: E402


def delivered(message_id: str) -> dict:
    """Whether the bridge has mapped a sent Matrix event to a LINE message."""
    db = sqlite3.connect(f"file:{line_mcp.DATA_DIR / 'bridge' / 'bridge.db'}?mode=ro", uri=True)
    try:
        row = db.execute("SELECT id FROM message WHERE mxid = ?", (message_id,)).fetchone()
    finally:
        db.close()
    return {"message_id": message_id, "delivered_to_line": bool(row and row[0])}


def main() -> None:
    logging.disable(logging.CRITICAL)
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("chats")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=30)
    p = sub.add_parser("read")
    p.add_argument("chat_id")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--before")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--chat")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("send")
    p.add_argument("chat_id")
    p.add_argument("text")
    p.add_argument("--reply-to")
    p.add_argument("--confirmed", action="store_true")
    p = sub.add_parser("media")
    p.add_argument("chat_id")
    p.add_argument("message_id")
    p = sub.add_parser("send-media")
    p.add_argument("chat_id")
    p.add_argument("file_path")
    p.add_argument("--reply-to")
    p.add_argument("--confirmed", action="store_true")
    p = sub.add_parser("delivered")
    p.add_argument("message_id")
    a = ap.parse_args()

    if a.cmd == "status":
        out = line_mcp.line_status()
    elif a.cmd == "chats":
        out = line_mcp.line_list_chats(a.query, a.limit)
    elif a.cmd == "read":
        out = line_mcp.line_read_messages(a.chat_id, a.limit, a.before)
    elif a.cmd == "search":
        out = line_mcp.line_search_messages(a.query, a.chat, a.limit)
    elif a.cmd == "send":
        if not a.confirmed:
            sys.exit("refusing to send without --confirmed (get the user's approval of the exact text and chat first)")
        out = line_mcp.line_send_message(a.chat_id, a.text, a.reply_to)
    elif a.cmd == "media":
        out = line_mcp.line_get_media(a.chat_id, a.message_id)
    elif a.cmd == "send-media":
        if not a.confirmed:
            sys.exit("refusing to send without --confirmed (get the user's approval of the exact file and chat first)")
        out = line_mcp.line_send_media(a.chat_id, a.file_path, a.reply_to)
    else:
        out = delivered(a.message_id)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
