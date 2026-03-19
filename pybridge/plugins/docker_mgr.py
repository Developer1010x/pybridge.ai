"""
plugins/docker_mgr.py — Docker container management.

Commands:
  docker ps               → list running containers
  docker ps all           → list all containers including stopped
  docker logs <name>      → last 50 lines of container logs
  docker logs <name> 100  → last N lines
  docker restart <name>   → restart container
  docker stop <name>      → stop container
  docker start <name>     → start container
  docker stats            → CPU/mem usage of all containers
  docker images           → list images
  docker pull <image>     → pull latest image
  docker exec <name> <cmd>→ run command inside container
  compose up              → docker compose up -d
  compose down            → docker compose down
  compose logs            → docker compose logs --tail=50
"""

import shutil
import subprocess
import logging

log = logging.getLogger("pybridge.docker")


def _docker(args: list[str], timeout: int = 30) -> str:
    if not shutil.which("docker"):
        return "Docker not found. Install Docker: https://docs.docker.com/get-docker/"
    try:
        r = subprocess.run(
            ["docker"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        out = r.stdout.strip()
        err = r.stderr.strip()
        return (out or err or "(no output)")[:3000]
    except subprocess.TimeoutExpired:
        return f"Docker command timed out ({timeout}s)"
    except Exception as e:
        return f"Docker error: {e}"


def _compose(args: list[str], timeout: int = 60) -> str:
    cmd = None
    if shutil.which("docker"):
        # Try `docker compose` (v2)
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=5)
            cmd = ["docker", "compose"] + args
        except Exception:
            pass
    if not cmd and shutil.which("docker-compose"):
        cmd = ["docker-compose"] + args
    if not cmd:
        return "docker compose not found."
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout.strip() or r.stderr.strip() or "(no output)")[:3000]
    except subprocess.TimeoutExpired:
        return "docker compose command timed out"
    except Exception as e:
        return f"compose error: {e}"


def handle(cmd: str, args: str) -> str:
    parts = args.strip().split()

    # List containers
    if cmd in ("docker ps", "containers"):
        if "all" in args.lower():
            return _docker(["ps", "-a", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"])
        return _docker(["ps", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"])

    # Logs
    if cmd == "docker logs":
        if not parts:
            return "Usage: docker logs <container> [lines]"
        name = parts[0]
        n = parts[1] if len(parts) > 1 and parts[1].isdigit() else "50"
        return _docker(["logs", "--tail", n, name])

    # Restart
    if cmd == "docker restart":
        if not parts:
            return "Usage: docker restart <container>"
        return _docker(["restart", parts[0]])

    # Stop
    if cmd == "docker stop":
        if not parts:
            return "Usage: docker stop <container>"
        return _docker(["stop", parts[0]])

    # Start
    if cmd == "docker start":
        if not parts:
            return "Usage: docker start <container>"
        return _docker(["start", parts[0]])

    # Stats
    if cmd == "docker stats":
        return _docker(["stats", "--no-stream", "--format",
                        "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"])

    # Images
    if cmd == "docker images":
        return _docker(["images", "--format", "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"])

    # Pull
    if cmd == "docker pull":
        if not parts:
            return "Usage: docker pull <image>"
        return _docker(["pull", parts[0]], timeout=120)

    # Exec
    if cmd == "docker exec":
        if len(parts) < 2:
            return "Usage: docker exec <container> <command>"
        name = parts[0]
        exec_cmd = parts[1:]
        return _docker(["exec", name] + exec_cmd, timeout=30)

    # Remove stopped containers
    if cmd in ("docker prune", "docker clean"):
        return _docker(["container", "prune", "-f"])

    # Compose
    if cmd == "compose up":
        return _compose(["up", "-d"])

    if cmd == "compose down":
        return _compose(["down"])

    if cmd == "compose logs":
        n = parts[0] if parts and parts[0].isdigit() else "50"
        return _compose(["logs", "--tail", n])

    if cmd == "compose restart":
        svc = parts[0] if parts else ""
        return _compose(["restart", svc] if svc else ["restart"])

    if cmd == "compose pull":
        return _compose(["pull"], timeout=120)

    if cmd == "compose ps":
        return _compose(["ps"])

    return f"Unknown docker command: {cmd}"
