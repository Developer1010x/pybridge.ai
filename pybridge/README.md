# PyBridge — AI Remote Control from Phone

Control **Claude / Codex / Ollama** from your phone via **Email**, **Telegram**, **WhatsApp**, or **iMessage**.

```
Phone (1 authorized contact)
  │ Email TLS / Telegram / WhatsApp / iMessage
  ▼
PyBridge — security gate + channel handler
  │ direct API calls
  ├── Claude  (Anthropic API)
  ├── Codex   (OpenAI API)
  └── Ollama  (local, no API key)
```

## Setup

```bash
cd pybridge
pip install -r requirements.txt
```

Edit `config.json` (or create a `.env` file) with:
- API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
- Channel credentials (see below)

## Run

```bash
python main.py
```

## Control Panel (GUI)

A web-based dashboard is available to manage config, channels, models, and security:

```bash
python control-panel/server.py
# Open http://127.0.0.1:9090
```

## Channels

### Email (Gmail)
1. Google Account → Security → 2-Step Verification → App Passwords
2. Create one for "Mail"
3. Set `email.enabled: true` in config.json
4. Add your Gmail + app password, and your phone email in `allowed_senders`

### Telegram
1. Message @BotFather on Telegram → `/newbot`
2. Copy the bot token into config.json
3. Get your user ID from @userinfobot
4. Set `telegram.enabled: true`

### WhatsApp
1. Set `whatsapp.enabled: true` (default)
2. Run PyBridge — a QR code window will appear
3. Scan with WhatsApp → Settings → Linked Devices → Link a Device

### iMessage (macOS only)
1. Grant "Full Disk Access" to Terminal in System Settings
2. Set `imessage.enabled: true`
3. Add your phone number to `allowed_handles`

## Environment Variables (`.env`)

Instead of editing config.json directly, create a `.env` file:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=your-app-password
TELEGRAM_BOT_TOKEN=123456:ABC...
HMAC_SECRET=your-random-secret
WHATSAPP_NUMBER=+1234567890
```

## Commands (send from phone)

| Command | Action |
|---------|--------|
| `use claude` | Switch to Claude |
| `use codex` | Switch to OpenAI/Codex |
| `use ollama` | Switch to local Ollama |
| `use ollama mistral` | Use specific Ollama model |
| `model` / `models` | Show current / list all |
| `ss` / `screenshot` | Take screenshot |
| `record 10` | Record screen (10s) |
| `stream` / `stopstream` | Live screen stream |
| `meet zoom/google/teams` | Start video meeting |
| `git status` / `log` / `diff` | Git info |
| `pr list` / `pr create` | Pull requests |
| `ps` / `kill` / `cpu` / `mem` | System monitor |
| `docker ps` / `logs` / `restart` | Docker management |
| `py <code>` / `node <code>` | Run code snippets |
| `read <file>` / `search <pattern>` | File operations |
| `every 30m <cmd>` / `at 09:00 <cmd>` | Scheduled tasks |
| `watch <logfile>` | Log watching + alerts |
| `browse <url>` | Screenshot a URL |
| `clip` / `copy <text>` | Clipboard |
| `run <cmd>` | Any terminal command |
| `clear` | Reset conversation |
| `help` | Show all commands |

## Security

- **One authorized contact** per channel (allowlists)
- **Prompt injection detection** — blocks known injection patterns
- **Rate limiting** — configurable per-minute limit (default 20)
- **Message sanitization** — strips control characters, enforces max length
- **HMAC signing** — optional message integrity verification
- **TLS** — all external communications encrypted

## Plugins

PyBridge ships with 11 plugins: `git_github`, `code_runner`, `file_ops`, `docker_mgr`, `process_monitor`, `scheduler`, `log_watcher`, `browser`, `clipboard`, `packages`, `vscode`.
