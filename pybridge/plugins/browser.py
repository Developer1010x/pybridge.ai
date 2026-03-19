from __future__ import annotations
"""
plugins/browser.py — Browser automation via Playwright.

Commands:
  browse https://example.com          → screenshot a URL
  browse https://example.com mobile   → mobile viewport
  title https://example.com           → get page title + meta description
  fetch https://example.com           → get page text content (no JS)
"""

import os
import shutil
import tempfile
import logging
import urllib.request
import urllib.error

log = logging.getLogger("pybridge.browser")


def _playwright_available() -> bool:
    try:
        import playwright
        return True
    except ImportError:
        return False


def screenshot_url(url: str, mobile: bool = False) -> tuple[str | None, str]:
    """Take a screenshot of a URL. Returns (file_path, message)."""
    if not url.startswith("http"):
        url = "https://" + url

    if not _playwright_available():
        return None, (
            "Playwright not installed.\n"
            "Install: pip install playwright && playwright install chromium"
        )

    try:
        from playwright.sync_api import sync_playwright

        path = tempfile.mktemp(suffix=".png")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            viewport = {"width": 390, "height": 844} if mobile else {"width": 1280, "height": 800}
            context = browser.new_context(viewport=viewport)
            page = context.new_page()
            page.goto(url, timeout=15000, wait_until="networkidle")
            page.screenshot(path=path, full_page=False)
            title = page.title()
            browser.close()

        return path, f"Screenshot of: {url}\nTitle: {title}"

    except Exception as e:
        return None, f"Browser screenshot failed: {e}"


def get_page_title(url: str) -> str:
    """Get page title and meta description without JS."""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 PyBridge/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(50000).decode("utf-8", errors="ignore")

        import re
        title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
        desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', raw, re.IGNORECASE)
        og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', raw, re.IGNORECASE)

        result = f"URL: {url}\n"
        result += f"Title: {title.group(1).strip()}\n" if title else ""
        result += f"OG Title: {og_title.group(1).strip()}\n" if og_title else ""
        result += f"Description: {desc.group(1).strip()}\n" if desc else ""
        return result or "Could not extract page info."

    except Exception as e:
        return f"Could not fetch {url}: {e}"


def fetch_text(url: str) -> str:
    """Fetch plain text content of a page (no JS, strips HTML)."""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 PyBridge/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(100000).decode("utf-8", errors="ignore")

        import re
        # Remove scripts, styles, tags
        raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = re.sub(r"\s+", " ", raw).strip()

        return f"{url}:\n\n{raw[:3000]}"

    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return f"Fetch failed: {e}"


def handle(cmd: str, args: str) -> tuple[str, str | None]:
    """Returns (text_reply, file_path_or_None)."""
    parts = args.strip().split()
    url = parts[0] if parts else ""

    if not url:
        return "Usage: browse <url>", None

    if cmd == "browse":
        mobile = len(parts) > 1 and "mobile" in parts[1].lower()
        path, msg = screenshot_url(url, mobile)
        return msg, path

    if cmd == "title":
        return get_page_title(url), None

    if cmd in ("fetch", "curl"):
        return fetch_text(url), None

    return f"Unknown browser command: {cmd}", None
