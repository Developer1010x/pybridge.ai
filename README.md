# pybridge.ai

**Text your laptop and it does things.** Send a message from WhatsApp, Telegram,
Email or iMessage — PyBridge checks it came from you, routes it through a
12-plugin command router or an LLM, and replies with the answer, a screenshot
or a screen recording.

```
Phone (allowlisted contacts only)
  │ WhatsApp / Telegram / Email / iMessage / local REPL
  ▼
PyBridge — security gate → command router → 12 plugins
  │                                       ↘ falls through to the AI engine
  ├── Anthropic · OpenAI · Gemini · Groq · Mistral   (API key)
  ├── Ollama                                          (local, free, no key)
  └── OpenCode                                        (local server)
        ordered fallback chain · retry with backoff · per-model cooldowns
```

Runs on **Linux, macOS and Windows**. The daemon, the router and the control
panel are **pure standard library** — `pip install` is only needed for optional
extras like the Telegram channel or the browser plugin.

## Try it in 20 seconds — no phone, no API key

```bash
git clone https://github.com/Developer1010x/pybridge.ai.git
cd pybridge.ai/pybridge

python3 main.py --exec "git status"
python3 main.py --exec "py print(6*7)"
python3 main.py --repl              # interactive: same router your phone talks to
```

```
pybridge> sql SELECT 1+1
2
  (3 ms)
pybridge> ping 1.1.1.1
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=8.31 ms
  (3104 ms)
pybridge> what changed in this repo today
[ollama]

…
```

Anything not recognised as a command goes to the AI. With
[Ollama](https://ollama.com) running locally that costs nothing and needs no key.

## Control Panel

```bash
python3 control-panel/server.py
#   Open: http://127.0.0.1:9090/?token=<token printed here>
```

Zero dependencies, single HTML file. Dashboard with live service status and a
config health check, plus pages for channels, contacts, models, security and
the full phone-command reference.

The panel can edit the contact allowlist — i.e. it decides who is allowed to
run shell commands on this machine — so it is **token-authenticated and bound
to `127.0.0.1`** by default. The token is generated on first run and stored in
`~/.pybridge/panel_token`; pin it with `PANEL_TOKEN=…`.

`main.py` does **not** start the panel: they are two independent processes
(the Docker entrypoint runs both).

## Quick Start (Docker)

```bash
cp pybridge/.env.example pybridge/.env    # do this BEFORE the first `up`
docker compose up -d
docker compose logs pybridge | grep token # your panel URL
```

Compose publishes the panel on `127.0.0.1:9090` only.

## Quick Start (Native)

```bash
cd pybridge
pip install -r requirements.txt   # optional — see the comments in that file
python main.py                    # runs the channels enabled in config.json
```

All four phone channels ship **disabled**: enable one in `config.json` or in the
control panel, and add yourself to its allowlist, before the daemon will answer
anything.

## Features

**5 channels** — WhatsApp, Telegram, Email (Gmail), iMessage (macOS), local REPL

**7 AI providers** — Anthropic, OpenAI, Gemini, Groq, Mistral, Ollama, OpenCode.
All written against `urllib` directly, with an ordered fallback chain,
exponential backoff with jitter, error classification and per-model cooldowns
(`pybridge/engine/_direct.py`). The Anthropic Agent SDK is used when installed.

**12 plugins** — git/GitHub, Docker, code runner (Python/Node/Bash/Go/Ruby/SQL/HTTP),
file ops, process monitor, network diagnostics, scheduler, log watcher, browser
automation, clipboard, VS Code, package audits

**Security** — per-channel contact allowlists, prompt-injection detection, rate
limiting, message sanitization, token-authenticated control panel

**Screen tools** — screenshot, screen recording, live MJPEG stream, meeting
launcher (Zoom / Google Meet / Teams)

## Phone Commands

| Command | Action |
|---------|--------|
| `use claude / codex / ollama` | Switch AI model |
| `ss` | Screenshot |
| `git status` / `pr list` | Git & GitHub |
| `docker ps` / `docker logs` | Container management |
| `ping <host>` / `dns <host>` | Network reachability & DNS |
| `myip` / `portcheck <host> <port>` | Public IP & TCP port probe |
| `httpcheck <url>` | HTTP status + latency |
| `py print("hello")` | Run code |
| `every 30m screenshot` | Scheduled tasks |
| `run <cmd>` | Any terminal command |
| `help` | Show all commands |

Anything else is forwarded to the AI. Words that are both commands and English
(`find`, `read`, `open`, `search`, `get`, `go`) only reach a plugin when the
argument looks like an argument — `find *.py` greps, `find me a good restaurant`
goes to the model.

## Tests

```bash
python3 -m unittest discover -s tests -v   # 33 hermetic tests, no network
cd pybridge && python3 test_run.py         # live smoke test on this machine
```

## Project Structure

```
pybridge.ai/
├── pybridge/                  # Core daemon
│   ├── main.py                # Entry point, CLI and command router
│   ├── security.py            # Allowlists, rate limiting, injection protection
│   ├── screen.py              # Screenshot, recording, live stream
│   ├── channels/              # whatsapp · imessage · repl
│   ├── engine/                # session · runner · providers · _direct
│   └── plugins/               # 12 built-in plugins
├── control-panel/             # Web GUI (stdlib http.server + one HTML file)
├── tests/                     # Hermetic unit tests
├── Dockerfile                 # Python 3.11 + Node 20 + Chromium
└── docker-compose.yml
```

## Configuration

### Environment Variables (`.env`)

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=123456:ABC...
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=your-app-password
WHATSAPP_NUMBER=+1234567890
```

Panel-only variables: `PANEL_TOKEN`, `PANEL_HOST`, `PANEL_PORT`,
`PANEL_AUTH=off`.

### Docker Notes

- **WhatsApp**: the QR code appears in `docker compose logs -f`. Auth is written
  to `$WHATSAPP_AUTH_DIR` (`/data/whatsapp-auth`), which compose backs with the
  `pybridge-whatsapp` named volume, so it survives `docker compose up --force-recreate`.
- **Control panel**: bound to `0.0.0.0` inside the container so the published
  port reaches it, and published on `127.0.0.1` only. The token is still required.
- **iMessage**: macOS only, not available in Docker.
- **Screen capture**: needs X11 forwarding on Linux; unavailable headless.

## Security notes, honestly

- `run <cmd>` executes arbitrary shell as the daemon user, and the Agent SDK
  path runs with `permission_mode="bypassPermissions"`. That is the product.
  **The contact allowlist is the security boundary** — treat it like an SSH key.
- The control panel requires a token and listens on loopback. Do not publish it
  to a LAN without a TLS reverse proxy in front.
- The WhatsApp bridge listens on `127.0.0.1:8766` and is not authenticated;
  anything local that can reach that port can inject messages.
- `security.sign_message` / `verify_signature` implement HMAC-SHA256 but no
  shipped channel calls them — they are scaffolding for a future webhook
  transport, not an active protection.

## License

[MIT](LICENSE)
