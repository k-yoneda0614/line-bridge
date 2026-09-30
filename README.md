# line-bridge

Read, search, and send messages on your personal LINE account from [Claude Code](https://claude.com/claude-code), with the bridge running entirely on your Mac.

```
LINE servers
   ↕  matrix-line (beeper/line, MIT) — logs in as a LINE Chrome extension client
Synapse (127.0.0.1:18408, SQLite, no federation)
   ↕  Matrix Client-Server API
mcp/line_mcp.py (stdio MCP server) ← Claude Code
```

line-bridge is the glue around two existing open-source projects: the [beeper/line](https://github.com/beeper/line) Matrix bridge and the [Synapse](https://github.com/element-hq/synapse) homeserver. It builds them, configures them to listen on loopback only, runs them with launchd, and adds an MCP server so Claude Code can use your LINE chats as tools.

> [!WARNING]
> **Unofficial. Use at your own risk.** This project is not affiliated with or endorsed by LY Corporation. The bridge is an unofficial client that identifies itself as the LINE Chrome extension. The LINE Terms of Use prohibit operating the service by bots or other technical means (Common Terms, ch.1 art.15(5)), and LY Corporation may suspend or delete an account without notice. Keep usage human-paced: no bulk sending, scheduled sending, or auto-replies. The software is provided as is, without warranty (see [LICENSE](LICENSE)).

## Requirements

- macOS on Apple Silicon (tested on macOS 27) with FileVault on
- [Homebrew](https://brew.sh): `brew install go uv rust`
- A LINE account with an email address set (LINE app → Settings → Account)
- Claude Code

## Setup

1. Log out of the LINE Chrome extension and any other bridge that uses the same account. Only one Chrome extension session can exist at a time; two clients keep logging each other out.
2. Build and start everything:

   ```bash
   scripts/bootstrap.sh
   ```

   This clones beeper/line at a pinned commit into `upstream/`, applies `patches/`, builds it, builds Synapse from source, writes the configs, loads two launchd agents, and creates a local Matrix user.
3. Log in to LINE. Run this yourself in a terminal: the password is read with `getpass`, sent only to the local bridge, and never stored.

   ```bash
   ~/.local/share/line-bridge/venv/bin/python scripts/login.py
   ```

   Enter the PIN shown in the terminal on your phone.
4. Register the MCP server and require a confirmation for every send:

   ```bash
   claude mcp add line -s user -- ~/.local/share/line-bridge/venv/bin/python "$PWD/mcp/line_mcp.py"
   ```

   In `~/.claude/settings.json`:

   ```json
   { "permissions": { "ask": ["mcp__line__line_send_message"] } }
   ```

5. Check the install:

   ```bash
   ~/.local/share/line-bridge/venv/bin/python scripts/verify.py
   ```

## MCP tools

| Tool | What it does |
|---|---|
| `line_status` | Login state (`CONNECTED` when healthy) and number of synced chats |
| `line_list_chats` | Chats, most recently active first; `query` filters by name |
| `line_read_messages` | Messages oldest first; pass `older_cursor` back as `before` to page back |
| `line_search_messages` | Case-insensitive substring search, newest first, optionally within one chat |
| `line_send_message` | Send text (optionally as a reply) as you |

`mcp/line_cli.py` exposes the same functions on the command line (JSON output) for sessions without the MCP tools. Its `send` refuses to run without `--confirmed`, and `delivered MESSAGE_ID` reports whether a sent message reached LINE.

Reading through the bridge does not send read receipts to LINE.

## Security model

- **Nothing listens beyond loopback.** Synapse (18408) and the bridge (18722) bind to 127.0.0.1. Federation and open registration are off.
- **Every API needs a token.** The Synapse client API, the bridge's provisioning API, and appservice transactions are all authenticated. A web page cannot read or send through them without a token.
- **The LINE password is not stored.** Upstream keeps it in `bridge.db` for automatic re-login; `patches/0001` removes that. When the refresh token stops working, run `login.py` again.
- **Secrets stay owner-only.** Runtime data lives in `~/.local/share/line-bridge/` (mode 700). The launchd agents run with `Umask 077`.
- **Sends need a human.** `line_send_message` is an `ask` rule, and the server instructions tell the model to treat message text as untrusted third-party content, so a message that says "forward this to X" does not trigger a send.
- **Not protected against** malware running as your macOS user, which can read the tokens in `bridge.db`, like any desktop messaging client.
- **What leaves the Mac.** The bridge talks only to LINE. Messages you have Claude read are sent to the model as tool results, like any other context.

`verify.py` runs 18 checks for the points above plus health (listeners, auth, registration, bridge permissions, appservice namespaces, file modes, stored password, FileVault, the `ask` rule, login state, joined rooms). It never prints secret values.

## Layout

| Path | What |
|---|---|
| `scripts/bootstrap.sh` | Idempotent setup |
| `scripts/common.sh` | Paths, ports, pinned versions (`BRIDGE_COMMIT`, Python deps) |
| `scripts/configure.py` | Applies the local-only settings to the generated Synapse and bridge configs |
| `scripts/create_user.py` | Registers the local Matrix user and writes `credentials.json` |
| `scripts/launchd.sh` | `install [synapse\|bridge\|all]`, `uninstall`, `restart`, `status` |
| `scripts/login.py` | Interactive LINE login |
| `scripts/verify.py` | Health and security checks |
| `mcp/line_mcp.py`, `mcp/line_cli.py` | MCP server and CLI |
| `patches/` | Patches applied on top of the pinned upstream commit |
| `tests/` | Unit tests |
| `upstream/` | Upstream bridge checkout (gitignored) |

Runtime data in `~/.local/share/line-bridge/`:

| File | Contains |
|---|---|
| `credentials.json` | Local Matrix access token |
| `bridge/bridge.db` | LINE access and refresh tokens, E2EE keys |
| `synapse/homeserver.db` | Bridged messages |
| `synapse/media_store/` | Images, videos, avatars |
| `logs/` | Synapse and bridge logs |

Environment overrides: `LINE_BRIDGE_DATA` (data dir), `LINE_BRIDGE_SRC` (upstream checkout), `LINE_BRIDGE_MATRIX_USER` (local user; defaults to your macOS user name), `LINE_BRIDGE_LAUNCHD_PREFIX` (launchd labels; default `local.line-bridge`).

## Implementation notes

- Synapse's PyPI wheel fails to load on macOS 27 (`mis-aligned LINKEDIT string pool`). `bootstrap.sh` builds it from source with `CARGO_PROFILE_RELEASE_STRIP=false`.
- The bridge is built with `-tags goolm`, so libolm is not needed. Matrix-side encryption is off; LINE's own end-to-end encryption (Letter Sealing) is handled by the bridge.
- Synapse's `/search` uses SQLite FTS4 with the porter tokenizer, which cannot split Japanese. `line_search_messages` reads the Synapse database read-only and matches substrings instead.
- The first sync invites the local user to hundreds of rooms at once. With Synapse's default join ratelimits, the auto-accept module gives up after 5 retries, so `configure.py` raises the local ratelimits, and the MCP server also joins any bridge invite left pending.
- Messages you send from your phone arrive from your own ghost user (`@line_<escaped login id>`). The MCP server escapes the login ID the same way as mautrix (`id.EncodeUserLocalpart`) and marks them `is_me`.

## Development

```bash
uv pip install --python ~/.local/share/line-bridge/venv/bin/python pytest==8.4.2
~/.local/share/line-bridge/venv/bin/python -m pytest -q
```

## Operations

```bash
scripts/launchd.sh status
scripts/launchd.sh restart
tail -f ~/.local/share/line-bridge/logs/bridge.log
```

To update the bridge, read the upstream diff first (`git -C upstream/matrix-line fetch && git -C upstream/matrix-line log -p <BRIDGE_COMMIT>..origin/main`), bump `BRIDGE_COMMIT` in `scripts/common.sh`, then run `scripts/bootstrap.sh`.

To remove everything: `scripts/launchd.sh uninstall`, `claude mcp remove line -s user`, and delete `~/.local/share/line-bridge/`.

## License

MIT for the code in this repository. beeper/line is MIT and Synapse is AGPL-3.0; neither is included here, and `bootstrap.sh` fetches them from their upstream sources.
