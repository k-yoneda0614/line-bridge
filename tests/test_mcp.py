import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
import line_mcp  # noqa: E402

ME = "@me:line.local"


class FakeHTTP:
    def __init__(self):
        self.posts = []

    def post(self, path, json=None):
        self.posts.append(path)


def make_matrix() -> line_mcp.Matrix:
    m = object.__new__(line_mcp.Matrix)
    m.user_id = ME
    m.server_name = "line.local"
    m.http = FakeHTTP()
    m.rooms = {}
    m.members = {}
    m.own_ghosts = {"@line_u123:line.local"}
    return m


def invite(sender: str, target: str = ME) -> dict:
    return {"invite_state": {"events": [{"type": "m.room.member", "state_key": target, "sender": sender}]}}


def test_accepts_only_bridge_invites():
    m = make_matrix()
    m.accept_bridge_invites(
        {
            "!bot:line.local": invite("@linebot:line.local"),
            "!ghost:line.local": invite("@line_uabc:line.local"),
            "!remote:evil.org": invite("@linebot:evil.org"),
            "!local-human:line.local": invite("@mallory:line.local"),
            "!lookalike:line.local": invite("@linebot2:line.local"),
            "!other-target:line.local": invite("@linebot:line.local", target="@someone:line.local"),
        }
    )
    assert m.http.posts == [
        "/_matrix/client/v3/rooms/!bot:line.local/join",
        "/_matrix/client/v3/rooms/!ghost:line.local/join",
    ]


def test_format_event_marks_own_messages_and_replies():
    m = make_matrix()
    m.members["!r"] = {"@line_uabc:line.local": "Alice"}
    ev = {
        "type": "m.room.message",
        "event_id": "$2",
        "sender": "@line_uabc:line.local",
        "origin_server_ts": 0,
        "content": {"msgtype": "m.image", "body": "photo.jpg", "m.relates_to": {"m.in_reply_to": {"event_id": "$1"}}},
    }
    out = m.format_event("!r", ev)
    assert out["sender"] == "Alice"
    assert out["type"] == "image"
    assert out["is_me"] is False
    assert out["reply_to"] == "$1"
    assert out["time"] == "1970-01-01 09:00"  # epoch in JST

    mine = m.format_event("!r", {"type": "m.room.message", "sender": "@line_u123:line.local", "content": {"msgtype": "m.text", "body": "hi"}})
    assert mine["is_me"] is True
    sticker = m.format_event("!r", {"type": "m.sticker", "sender": ME, "content": {"body": "sticker"}})
    assert sticker["type"] == "sticker" and sticker["is_me"] is True


def test_bot_management_room_is_hidden():
    m = make_matrix()
    assert m.is_bot_room({"name": None, "heroes": ["@linebot:line.local"]})
    assert not m.is_bot_room({"name": "Family", "heroes": ["@linebot:line.local"]})
    assert not m.is_bot_room({"name": None, "heroes": ["@line_uabc:line.local"]})


def test_encode_localpart_matches_mautrix():
    # Escaping of the bridge's ghost user IDs (mautrix-go id.EncodeUserLocalpart).
    assert line_mcp.encode_localpart("UA_BcD") == "_u_a___bc_d"
    assert line_mcp.encode_localpart("u-3.x+9") == "u-3.x+9"
    assert line_mcp.encode_localpart("a@b") == "a=40b"
