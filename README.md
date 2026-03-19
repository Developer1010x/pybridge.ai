# pybridge.ai

**Control AI from your phone.** Send messages via WhatsApp, Telegram, Email, or iMessage — PyBridge routes them to Claude, OpenAI, or local Ollama and replies back.

```
Phone (1 authorized contact)
  | WhatsApp / Telegram / Email / iMessage
  v
PyBridge (security gate + AI engine)
  |
  +-- Claude   (Anthropic API)
  +-- Codex    (OpenAI API)
  +-- Ollama   (local, free)
```

Works on **Linux, macOS, and Windows**.

## Quick Start (Docker)

```bash
git clone https://github.com/Developer1010x/pybridge.ai.git
cd pybridge.ai

# Configure
cp pybridge/.env.example pybridge/.env
# Edit pybridge/.env with your API keys

# Run
docker compose up -d

# Open control panel
open http://localhost:9090
```

## Quick Start (Native)

```bash
cd pybridge
pip install -r requirements.txt
# Edit config.json or create .env with API keys
python main.py
```

## Control Panel

Web dashboard at `http://localhost:9090` for managing:
- Channels (enable/disable WhatsApp, Telegram, Email, iMessage)
- Models (switch default, view fallback chain)
- Security (rate limits, prompt injection protection)
- Plugins (11 built-in: git, docker, code runner, scheduler, etc.)

```bash
# Standalone (without Docker)
python control-panel/server.py
```

## Features

**4 Channels** — WhatsApp, Telegram, Email (Gmail), iMessage (macOS)

**3 AI Providers** — Claude (Anthropic), GPT/Codex (OpenAI), Ollama (local) with automatic fallback

**11 Plugins** — Git/GitHub, Docker, code runner (Python/Node/Bash/Go/Ruby/SQL), file ops, process monitor, scheduler, log watcher, browser automation, clipboard, VS Code, package audits

**Security** — Rate limiting, prompt injection detection, message sanitization, sender allowlists, HMAC signing

**Screen Tools** — Screenshot, screen recording, live MJPEG stream, meeting launcher (Zoom/Google Meet/Teams)

## Phone Commands

| Command | Action |
|---------|--------|
| `use claude / codex / ollama` | Switch AI model |
| `ss` | Screenshot |
| `git status` / `pr list` | Git & GitHub |
| `docker ps` / `docker logs` | Container management |
| `py print("hello")` | Run code |
| `every 30m screenshot` | Scheduled tasks |
| `help` | Show all commands |

See the full command reference in the [control panel](http://localhost:9090) under "Commands".

## Project Structure

```
pybridge.ai/
├── pybridge/                  # Core daemon
│   ├── main.py                # Entry point + command router
│   ├── security.py            # Auth, rate limiting, injection protection
│   ├── screen.py              # Screenshot, recording, live stream
│   ├── meet.py                # Video meeting launcher
│   ├── config.json            # Configuration
│   ├── channels/              # WhatsApp, iMessage handlers
│   ├── engine/                # AI engine (session, runner, providers)
│   └── plugins/               # 11 built-in plugins
├── control-panel/             # Web GUI dashboard
│   ├── server.py              # Python HTTP server + API
│   └── static/index.html      # Frontend
├── Dockerfile                 # Multi-platform Docker image
├── docker-compose.yml         # One-command deployment
└── README.md
```

## Configuration

### Environment Variables (`.env`)

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=123456:ABC...
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=your-app-password
HMAC_SECRET=your-random-secret
WHATSAPP_NUMBER=+1234567890
```

### Docker Notes

- **WhatsApp**: QR code appears in container logs (`docker compose logs -f`). On first run, scan it with your phone. Auth persists across restarts via Docker volume.
- **iMessage**: Not available in Docker (requires macOS). Use native install for iMessage.
- **Screen capture**: Requires X11 forwarding on Linux. Not available in headless Docker.
- **Config changes**: Edit `pybridge/config.json` on host, restart container.

## License

MIT
