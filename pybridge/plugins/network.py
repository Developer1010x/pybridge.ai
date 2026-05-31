"""
plugins/network.py — Network diagnostics & connectivity checks.

Lets you debug a remote machine's network from your phone without an LLM:
reachability, DNS resolution, public/local IP, open-port probing and quick
HTTP health checks.

Commands:
  ping <host>           → ICMP reachability + round-trip time
  dns <host>            → resolve host to IP address(es)
  myip                  → public (WAN) IP address as seen from the internet
  localip               → local (LAN) IP address(es) of this machine
  portcheck <host> <p>  → test whether TCP port <p> is open on <host>
  httpcheck <url>       → HTTP status code + latency for a URL
  netinfo               → quick summary (local IP, public IP, hostname)
"""

import os
import socket
import platform
import subprocess
import shutil
import time
import logging

log = logging.getLogger("pybridge.network")
OS = platform.system()


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout.strip() or r.stderr.strip() or "(no output)")[:3000]
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return f"Timed out ({timeout}s)"
    except Exception as e:
        return f"Error: {e}"


def ping(host: str, count: int = 4) -> str:
    host = host.strip()
    if not host:
        return "Usage: ping <host>"
    if OS == "Windows":
        cmd = ["ping", "-n", str(count), host]
    else:
        cmd = ["ping", "-c", str(count), host]
    return _run(cmd, timeout=count + 10)


def dns_lookup(host: str) -> str:
    host = host.strip()
    if not host:
        return "Usage: dns <host>"
    try:
        # getaddrinfo covers both IPv4 and IPv6
        infos = socket.getaddrinfo(host, None)
        addrs = sorted({info[4][0] for info in infos})
        canonical = socket.getfqdn(host)
        lines = [f"{host} resolves to:"]
        for a in addrs:
            lines.append(f"  {a}")
        if canonical and canonical != host:
            lines.append(f"Canonical name: {canonical}")
        return "\n".join(lines)
    except socket.gaierror as e:
        return f"Could not resolve '{host}': {e}"
    except Exception as e:
        return f"DNS error: {e}"


def public_ip() -> str:
    """Public/WAN IP via stdlib HTTP, with a couple of fallback endpoints."""
    try:
        import urllib.request
        for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
            try:
                with urllib.request.urlopen(url, timeout=6) as resp:
                    ip = resp.read().decode().strip()
                    if ip:
                        return ip
            except Exception:
                continue
        return "Could not determine public IP (no endpoint reachable)."
    except Exception as e:
        return f"Public IP lookup failed: {e}"


def local_ip() -> str:
    """Best-effort local/LAN IP address(es)."""
    addrs = set()

    # Primary outbound interface trick — no traffic actually sent.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            addrs.add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass

    # All addresses associated with the hostname.
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if not ip.startswith("127.") and ip != "::1":
                addrs.add(ip)
    except Exception:
        pass

    if not addrs:
        return "Could not determine local IP."
    return "Local IP(s):\n" + "\n".join(f"  {a}" for a in sorted(addrs))


def port_check(host: str, port: int, timeout: float = 5.0) -> str:
    try:
        start = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = (time.monotonic() - start) * 1000
        return f"Port {port} on {host} is OPEN ({elapsed:.0f} ms)"
    except socket.timeout:
        return f"Port {port} on {host} timed out (filtered/closed)"
    except ConnectionRefusedError:
        return f"Port {port} on {host} is CLOSED (connection refused)"
    except socket.gaierror as e:
        return f"Could not resolve '{host}': {e}"
    except Exception as e:
        return f"Port {port} on {host}: {e}"


def http_check(url: str) -> str:
    url = url.strip()
    if not url:
        return "Usage: httpcheck <url>"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "PyBridge-netcheck"})
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = (time.monotonic() - start) * 1000
            code = resp.getcode()
            server = resp.headers.get("Server", "?")
            return f"{url}\n  Status : {code}\n  Latency: {elapsed:.0f} ms\n  Server : {server}"
    except Exception as e:
        # urllib raises HTTPError (a subclass) for 4xx/5xx — surface the code.
        code = getattr(e, "code", None)
        if code is not None:
            return f"{url}\n  Status : {code} ({getattr(e, 'reason', 'error')})"
        return f"{url}\n  Failed : {e}"


def net_info() -> str:
    hostname = socket.gethostname()
    parts = [
        "=== Network Info ===",
        f"Hostname  : {hostname}",
        "",
        local_ip(),
        "",
        f"Public IP : {public_ip()}",
    ]
    return "\n".join(parts)


def handle(cmd: str, args: str) -> str:
    args = (args or "").strip()

    if cmd == "ping":
        return ping(args)

    if cmd in ("dns", "resolve", "nslookup"):
        return dns_lookup(args)

    if cmd in ("myip", "publicip", "wanip"):
        return f"Public IP: {public_ip()}"

    if cmd in ("localip", "lanip"):
        return local_ip()

    if cmd in ("portcheck", "port"):
        toks = args.split()
        if len(toks) < 2 or not toks[1].isdigit():
            return "Usage: portcheck <host> <port>"
        return port_check(toks[0], int(toks[1]))

    if cmd in ("httpcheck", "httpstatus"):
        return http_check(args)

    if cmd in ("netinfo", "network"):
        return net_info()

    return f"Unknown network command: {cmd}"
