/**
 * WhatsApp Bridge Server
 * Uses whatsapp-web.js (Baileys) to connect WhatsApp Web to PyBridge.
 *
 * Flow:
 *   1. Run this once → scan QR code with WhatsApp on your phone
 *   2. Session is saved — no need to scan again
 *   3. PyBridge polls /messages and POSTs to /send
 *
 * Ports: 8766 (HTTP bridge, localhost only)
 */

const { Client, LocalAuth } = require("whatsapp-web.js");
const express = require("express");
const qrcode = require("qrcode-terminal");
const fs = require("fs");
const path = require("path");

const app = express();
app.use(express.json());

// ── Config ────────────────────────────────────────────────────────────────────

const CONFIG_PATH = path.join(__dirname, "..", "config.json");
const config = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
const WA_CFG = config.whatsapp || {};
const ALLOWED_NUMBERS = (WA_CFG.allowed_numbers || []).map((n) =>
  n.replace(/[^0-9]/g, "") + "@c.us"
);
const PORT = WA_CFG.bridge_port || 8766;

// ── Message Queue ─────────────────────────────────────────────────────────────

const pendingMessages = [];
let isReady = false;
let currentQR = null;

// ── WhatsApp Client ───────────────────────────────────────────────────────────

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: path.join(__dirname, ".wwebjs_auth") }),
  webVersion: "2.3000.1017054429-alpha",
  webVersionCache: {
    type: "remote",
    remotePath:
      "https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/{version}.html",
  },
  puppeteer: {
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-accelerated-2d-canvas",
      "--no-first-run",
      "--no-zygote",
      "--disable-gpu",
    ],
  },
});

client.on("qr", (qr) => {
  currentQR = qr;
  console.log("[whatsapp] QR ready — waiting for scan...");
});

client.on("authenticated", () => {
  currentQR = null;
  console.log("[whatsapp] Authenticated.");
});

client.on("ready", () => {
  isReady = true;
  currentQR = null;
  console.log("[whatsapp] Ready. Bridge listening on port", PORT);
});

client.on("disconnected", (reason) => {
  isReady = false;
  console.log("[whatsapp] Disconnected:", reason);
});

function handleMsg(msg) {
  // Ignore groups and broadcasts
  if (msg.from.endsWith("@g.us") || msg.from === "status@broadcast") return;

  let senderNum, replyTo;

  if (msg.fromMe) {
    // Ignore our own bot replies to avoid feedback loop
    if (msg.body && msg.body.startsWith("[claude]")) return;
    // Message sent FROM the user's own phone.
    // Accept if: sent to a @lid (linked device = note-to-self), OR starts with "/"
    const toLinkedDevice = msg.to && msg.to.endsWith("@lid");
    const hasPrefix      = msg.body && msg.body.startsWith("/");
    if (!toLinkedDevice && !hasPrefix) return;
    senderNum = msg.from.replace("@c.us", "").replace(/@\S+/, "");
    replyTo   = msg.to; // reply to the same @lid chat
  } else {
    senderNum = msg.from.replace("@c.us", "");
    replyTo   = msg.from;
    // Authorization check for incoming messages
    if (ALLOWED_NUMBERS.length > 0 && !ALLOWED_NUMBERS.includes(msg.from)) {
      console.log(`[whatsapp] Blocked from unauthorized: ${senderNum}`);
      return;
    }
  }

  const body = msg.fromMe && msg.body.startsWith("/")
    ? msg.body.slice(1).trim()   // strip the "/" prefix
    : msg.body;

  if (!body) return;

  console.log(`[whatsapp] ${msg.fromMe ? "self" : "from"} ${senderNum}: ${body.substring(0, 60)}`);
  pendingMessages.push({
    from: replyTo,
    from_number: senderNum,
    body: body,
    timestamp: msg.timestamp,
    hasMedia: msg.hasMedia,
  });
}

client.on("message", (msg) => {
  console.log(`[DEBUG] message: from=${msg.from} to=${msg.to} fromMe=${msg.fromMe} body=${msg.body && msg.body.substring(0,40)}`);
  handleMsg(msg);
});
client.on("message_create", (msg) => {
  console.log(`[DEBUG] message_create: from=${msg.from} to=${msg.to} fromMe=${msg.fromMe} body=${msg.body && msg.body.substring(0,40)}`);
  handleMsg(msg);
});

client.initialize();

// ── HTTP API ──────────────────────────────────────────────────────────────────

// Poll for new incoming messages
app.get("/messages", (req, res) => {
  res.json(pendingMessages.splice(0));
});

// Send a message
app.post("/send", async (req, res) => {
  const { to, message } = req.body;
  if (!isReady) {
    return res.status(503).json({ ok: false, error: "WhatsApp not ready" });
  }
  try {
    // Support @c.us, @lid, and plain numbers
    const chatId = (to.includes("@c.us") || to.includes("@lid") || to.includes("@g.us"))
      ? to
      : to.replace(/[^0-9]/g, "") + "@c.us";
    await client.sendMessage(chatId, message);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

// Send an image
app.post("/send-image", async (req, res) => {
  const { to, image_path, caption } = req.body;
  if (!isReady) {
    return res.status(503).json({ ok: false, error: "WhatsApp not ready" });
  }
  try {
    const { MessageMedia } = require("whatsapp-web.js");
    const media = MessageMedia.fromFilePath(image_path);
    const chatId = (to.includes("@c.us") || to.includes("@lid") || to.includes("@g.us"))
      ? to
      : to.replace(/[^0-9]/g, "") + "@c.us";
    await client.sendMessage(chatId, media, { caption });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

// Send a video
app.post("/send-video", async (req, res) => {
  const { to, video_path, caption } = req.body;
  if (!isReady) {
    return res.status(503).json({ ok: false, error: "WhatsApp not ready" });
  }
  try {
    const { MessageMedia } = require("whatsapp-web.js");
    const media = MessageMedia.fromFilePath(video_path);
    const chatId = (to.includes("@c.us") || to.includes("@lid") || to.includes("@g.us"))
      ? to
      : to.replace(/[^0-9]/g, "") + "@c.us";
    await client.sendMessage(chatId, media, { caption });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

// QR code string for Python to render
app.get("/qr", (req, res) => {
  if (currentQR) {
    res.json({ qr: currentQR });
  } else {
    res.json({ qr: null, ready: isReady });
  }
});

// Status check
app.get("/status", (req, res) => {
  res.json({ ready: isReady, pending: pendingMessages.length });
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[whatsapp] Bridge server running on http://127.0.0.1:${PORT}`);
});
