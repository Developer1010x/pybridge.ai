"""
security.py — Authorization, prompt injection protection, MITM guards.

Only ONE authorized contact can control the daemon.
All messages are checked before being forwarded to the AI engine.
"""

import hmac
import hashlib
import time
import re
import logging
from collections import defaultdict

log = logging.getLogger("pybridge.security")

# ── Rate limiter ──────────────────────────────────────────────────────────────

_rate_buckets: dict[str, list[float]] = defaultdict(list)

def check_rate_limit(identity: str, max_per_minute: int) -> bool:
    """Returns True if allowed, False if rate limited."""
    now = time.time()
    window = 60.0
    timestamps = _rate_buckets[identity]
    # Drop old timestamps
    _rate_buckets[identity] = [t for t in timestamps if now - t < window]
    if len(_rate_buckets[identity]) >= max_per_minute:
        log.warning(f"Rate limit hit for {identity}")
        return False
    _rate_buckets[identity].append(now)
    return True

# ── Sender verification ───────────────────────────────────────────────────────

def verify_email_sender(sender: str, allowed: list[str]) -> bool:
    """Check email sender is in the authorized list (case-insensitive)."""
    sender = sender.strip().lower()
    allowed_lower = [a.strip().lower() for a in allowed]
    if sender not in allowed_lower:
        log.warning(f"BLOCKED email from unauthorized sender: {sender}")
        return False
    return True

def verify_telegram_user(user_id: int, allowed_ids: list[int]) -> bool:
    """Check Telegram user_id is in the authorized list."""
    if user_id not in allowed_ids:
        log.warning(f"BLOCKED Telegram message from unauthorized user_id: {user_id}")
        return False
    return True

# ── Prompt injection protection ───────────────────────────────────────────────

def check_prompt_injection(text: str, patterns: list[str]) -> tuple[bool, str]:
    """
    Returns (is_safe, reason).
    True = safe to forward. False = injection attempt detected.
    """
    lower = text.lower()
    for pattern in patterns:
        if pattern.lower() in lower:
            reason = f"Prompt injection pattern detected: '{pattern}'"
            log.warning(f"INJECTION BLOCKED: {reason} | text: {text[:80]}")
            return False, reason
    return True, ""

def sanitize_message(text: str, max_length: int) -> str:
    """Trim to max length and strip dangerous control characters."""
    text = text[:max_length]
    # Remove null bytes and other control chars except newlines/tabs
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()

# ── HMAC message signing (optional extra layer for Telegram webhooks) ─────────

def sign_message(secret: str, message: str) -> str:
    """Generate HMAC-SHA256 signature for a message."""
    return hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

def verify_signature(secret: str, message: str, signature: str) -> bool:
    """Verify HMAC-SHA256 signature."""
    expected = sign_message(secret, message)
    return hmac.compare_digest(expected, signature)

# ── Full message gate ─────────────────────────────────────────────────────────

def gate(
    text: str,
    identity: str,
    security_cfg: dict,
) -> tuple[bool, str]:
    """
    Run all security checks on incoming message.
    Returns (allowed, error_message).
    """
    max_len = security_cfg.get("max_message_length", 4000)
    rate_limit = security_cfg.get("rate_limit_per_minute", 20)
    block_injection = security_cfg.get("block_prompt_injection", True)
    patterns = security_cfg.get("injection_patterns", [])

    # 1. Rate limit
    if not check_rate_limit(identity, rate_limit):
        return False, "Rate limit exceeded. Wait a moment."

    # 2. Sanitize
    text = sanitize_message(text, max_len)
    if not text:
        return False, "Empty message."

    # 3. Prompt injection
    if block_injection:
        safe, reason = check_prompt_injection(text, patterns)
        if not safe:
            return False, f"Blocked: {reason}"

    return True, text
