"""
plugins/process_monitor.py — System & process monitoring.

Commands:
  ps                  → top 10 processes by CPU
  ps nginx            → find process by name
  kill nginx          → kill process by name
  kill 1234           → kill by PID
  ports               → ports in use + what's listening
  disk                → disk usage
  mem                 → memory usage
  cpu                 → CPU usage
  sys                 → full system overview
  uptime              → system uptime
"""

import os
import platform
import subprocess
import shutil
import logging

log = logging.getLogger("pybridge.process")
OS = platform.system()


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout.strip() or r.stderr.strip())[:3000]
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error: {e}"


def _psutil_available() -> bool:
    try:
        import psutil
        return True
    except ImportError:
        return False


def top_processes(n: int = 10, filter_name: str = "") -> str:
    if _psutil_available():
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                info = p.info
                if filter_name and filter_name.lower() not in info["name"].lower():
                    continue
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        procs.sort(key=lambda x: x["cpu_percent"] or 0, reverse=True)
        if not procs:
            return f"No processes found matching '{filter_name}'" if filter_name else "No processes"

        lines = [f"{'PID':>7}  {'CPU%':>6}  {'MEM%':>6}  {'STATUS':>10}  NAME"]
        lines.append("-" * 50)
        for p in procs[:n]:
            lines.append(
                f"{p['pid']:>7}  {p['cpu_percent'] or 0:>5.1f}%  "
                f"{p['memory_percent'] or 0:>5.1f}%  {p['status']:>10}  {p['name']}"
            )
        return "\n".join(lines)

    # Fallback
    if OS == "Windows":
        return _run(["tasklist", "/fo", "csv", "/nh"])
    return _run(["ps", "aux", "--sort=-%cpu"])


def kill_process(target: str) -> str:
    if _psutil_available():
        import psutil
        killed = []
        errors = []

        for p in psutil.process_iter(["pid", "name"]):
            try:
                name = p.info["name"]
                pid = str(p.info["pid"])
                if target.isdigit():
                    if pid == target:
                        p.kill()
                        killed.append(f"{name} (PID {pid})")
                elif target.lower() in name.lower():
                    p.kill()
                    killed.append(f"{name} (PID {pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                errors.append(str(e))

        if killed:
            return f"Killed: {', '.join(killed)}"
        return f"No process found matching '{target}'"

    # Fallback
    if OS == "Windows":
        if target.isdigit():
            return _run(["taskkill", "/PID", target, "/F"])
        return _run(["taskkill", "/IM", target, "/F"])
    if target.isdigit():
        return _run(["kill", "-9", target])
    return _run(["pkill", "-9", target])


def get_ports() -> str:
    if OS == "Windows":
        return _run(["netstat", "-ano"])
    if OS == "Darwin":
        return _run(["lsof", "-iTCP", "-sTCP:LISTEN", "-n", "-P"])
    return _run(["ss", "-tlnp"]) or _run(["netstat", "-tlnp"])


def get_disk() -> str:
    if _psutil_available():
        import psutil
        lines = [f"{'Mount':20}  {'Total':>10}  {'Used':>10}  {'Free':>10}  {'Use%':>6}"]
        lines.append("-" * 60)
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(
                    f"{part.mountpoint:20}  "
                    f"{_fmt(usage.total):>10}  "
                    f"{_fmt(usage.used):>10}  "
                    f"{_fmt(usage.free):>10}  "
                    f"{usage.percent:>5.1f}%"
                )
            except PermissionError:
                pass
        return "\n".join(lines)

    if OS == "Windows":
        return _run(["wmic", "logicaldisk", "get", "size,freespace,caption"])
    return _run(["df", "-h"])


def get_memory() -> str:
    if _psutil_available():
        import psutil
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return (
            f"RAM\n"
            f"  Total : {_fmt(vm.total)}\n"
            f"  Used  : {_fmt(vm.used)} ({vm.percent}%)\n"
            f"  Free  : {_fmt(vm.available)}\n\n"
            f"Swap\n"
            f"  Total : {_fmt(sw.total)}\n"
            f"  Used  : {_fmt(sw.used)} ({sw.percent}%)"
        )
    if OS == "Windows":
        return _run(["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize"])
    return _run(["free", "-h"])


def get_cpu() -> str:
    if _psutil_available():
        import psutil, time
        psutil.cpu_percent(interval=None)
        time.sleep(0.5)
        usage = psutil.cpu_percent(interval=None, percpu=True)
        overall = sum(usage) / len(usage)
        freq = psutil.cpu_freq()
        lines = [f"Overall CPU: {overall:.1f}%"]
        if freq:
            lines.append(f"Frequency : {freq.current:.0f} MHz")
        lines.append(f"Cores     : {psutil.cpu_count(logical=False)} physical, {psutil.cpu_count()} logical")
        lines.append("\nPer core:")
        for i, c in enumerate(usage):
            bar = "█" * int(c / 5)
            lines.append(f"  Core {i}: {c:>5.1f}%  {bar}")
        return "\n".join(lines)

    if OS == "Windows":
        return _run(["wmic", "cpu", "get", "loadpercentage"])
    return _run(["top", "-bn1"])


def get_uptime() -> str:
    if _psutil_available():
        import psutil, time
        boot = psutil.boot_time()
        uptime_s = int(time.time() - boot)
        d, r = divmod(uptime_s, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        return f"Uptime: {d}d {h}h {m}m {s}s"
    if OS == "Windows":
        return _run(["net", "statistics", "workstation"])
    return _run(["uptime"])


def get_sys_overview() -> str:
    parts = [
        f"=== System Overview ({OS}) ===",
        "",
        get_cpu(),
        "",
        get_memory(),
        "",
        get_disk(),
        "",
        get_uptime(),
    ]
    return "\n".join(parts)


def _fmt(bytes_val: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}PB"


def handle(cmd: str, args: str) -> str:
    if cmd == "ps":
        return top_processes(filter_name=args.strip())

    if cmd == "kill":
        target = args.strip()
        if not target:
            return "Usage: kill <name or PID>"
        return kill_process(target)

    if cmd in ("ports", "listening"):
        return get_ports()

    if cmd == "disk":
        return get_disk()

    if cmd in ("mem", "memory", "ram"):
        return get_memory()

    if cmd == "cpu":
        return get_cpu()

    if cmd in ("sys", "system", "overview"):
        return get_sys_overview()

    if cmd in ("uptime",):
        return get_uptime()

    return f"Unknown process command: {cmd}"
