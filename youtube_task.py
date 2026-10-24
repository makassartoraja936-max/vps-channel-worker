#!/usr/bin/env python3
"""
YouTube Automation Worker Module
================================
Automated browser interactions using Playwright Chromium:
- Navigates to YouTube
- Searches for keywords
- Plays videos for realistic watch sessions (5-10 minutes)
- Performs interactive actions (Likes, comments)
"""

import asyncio
import json
import logging
import os
import random
import shutil
import sys
import time
from urllib.parse import urlparse

import socket
import subprocess

try:
    from playwright_stealth import Stealth
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("YouTubeWorker")

PROFILE_DIR = os.path.expanduser("~/workspace/browser_profile")
BRIDGE_PORT = 8889
ACTIVITY_LOG_FILE = os.path.expanduser("~/workspace/browser_activity.log")


def log_activity(tag: str, text: str):
    """Logs browser and extension activity to file for real-time Hub streaming."""
    clean = str(text).replace("\r", " ").replace("\n", " ").strip()[:350]
    logger.info(f"[{tag}] {clean}")
    try:
        with open(ACTIVITY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] [{tag}] {clean}\n")
    except Exception:
        pass


def get_installed_extension_paths():
    """Scans user profile and workspace directories for installed unpacked extensions."""
    candidate_bases = [
        os.path.join(PROFILE_DIR, "Default", "Extensions"),
        os.path.join(PROFILE_DIR, "Extensions"),
        os.path.join(PROFILE_DIR, "extensions"),
        os.path.expanduser("~/workspace/extensions")
    ]
    paths = []
    seen = set()
    for ext_base in candidate_bases:
        if not os.path.exists(ext_base):
            continue
        try:
            for item in os.listdir(ext_base):
                item_path = os.path.join(ext_base, item)
                # Check if item itself is an extension root with manifest.json
                if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "manifest.json")):
                    if item_path not in seen:
                        seen.add(item_path)
                        paths.append(item_path)
                elif os.path.isdir(item_path):
                    # Check versioned subfolders (e.g. ext_id/1.0.0_0/manifest.json)
                    for v in os.listdir(item_path):
                        v_path = os.path.join(item_path, v)
                        if os.path.isdir(v_path) and os.path.exists(os.path.join(v_path, "manifest.json")):
                            if v_path not in seen:
                                seen.add(v_path)
                                paths.append(v_path)
        except Exception as e:
            logger.warning(f"Error scanning extensions in {ext_base}: {e}")
    return paths


def ensure_proxy_bridge_running():
    """Ensures local loopback proxy bridge is running on 127.0.0.1:8889."""
    # Check if port is already open
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", BRIDGE_PORT)) == 0:
            return True

    # Start proxy_bridge.py
    bridge_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_bridge.py")
    if os.path.exists(bridge_script):
        logger.info("Starting local loopback proxy bridge...")
        subprocess.Popen([sys.executable, bridge_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait up to 3 seconds for port to open
        for _ in range(30):
            time.sleep(0.1)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                s2.settimeout(0.2)
                if s2.connect_ex(("127.0.0.1", BRIDGE_PORT)) == 0:
                    logger.info("Local proxy bridge active on port 8889.")
                    return True
    return False


def ensure_virtual_display() -> bool:
    """Ensures Xvfb virtual display is running on :99 so Chromium runs with full GUI (headless=False) for 100% extension compatibility."""
    if os.environ.get("DISPLAY"):
        return True

    xvfb_bin = None
    for candidate in ["/usr/bin/Xvfb", "/usr/local/bin/Xvfb", "Xvfb"]:
        if os.path.exists(candidate) or shutil.which(candidate):
            xvfb_bin = candidate
            break

    # If Xvfb is missing after VM replacement, auto-install it quietly
    if not xvfb_bin:
        try:
            logger.info("Xvfb tidak ditemukan. Memasang paket xvfb secara otomatis...")
            subprocess.run(["sudo", "apt-get", "update", "-qq"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "xvfb"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists("/usr/bin/Xvfb") or shutil.which("Xvfb"):
                xvfb_bin = "/usr/bin/Xvfb"
        except Exception as e:
            logger.warning(f"Auto-install xvfb warning: {e}")

    if xvfb_bin:
        try:
            chk = subprocess.run(["pgrep", "-f", "Xvfb :99"], stdout=subprocess.DEVNULL)
            if chk.returncode != 0:
                logger.info("Starting Xvfb virtual display on :99 (1366x768x24)...")
                subprocess.Popen([xvfb_bin, ":99", "-screen", "0", "1366x768x24", "-nolisten", "tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1)
            os.environ["DISPLAY"] = ":99"
            logger.info("🖥️ Xvfb virtual display active on :99.")
            return True
        except Exception as e:
            logger.warning(f"Failed to start Xvfb: {e}")
    return False


def find_system_browser() -> str:
    """Finds genuine system browser binaries (Google Chrome, Thorium, or Chromium) if installed.
    Supports persistent portable Thorium in ~/workspace that survives any VM reboot or replacement!
    """
    candidates = [
        # 1. Permanent portable Thorium in persistent ~/workspace directory (NEVER lost on VM replacement)
        os.path.expanduser("~/workspace/thorium/opt/chromium.org/thorium/thorium-browser"),
        os.path.expanduser("~/workspace/thorium/opt/chromium.org/thorium/thorium"),
        os.path.expanduser("~/workspace/thorium/usr/bin/thorium-browser"),
        # 2. Installed system packages
        "/usr/bin/thorium-browser",
        "/opt/chromium.org/thorium/thorium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium"
    ]
    for c in candidates:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c

    # 3. If missing from system after VM replacement, auto-restore from cached .deb in ~/workspace
    cached_deb = os.path.expanduser("~/workspace/thorium.deb")
    thorium_target_dir = os.path.expanduser("~/workspace/thorium")
    if os.path.exists(cached_deb):
        try:
            logger.info("Auto-restoring persistent Thorium Browser from cached deb...")
            subprocess.run(["dpkg", "-x", cached_deb, thorium_target_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            portable = os.path.join(thorium_target_dir, "opt/chromium.org/thorium/thorium-browser")
            if os.path.exists(portable) and os.access(portable, os.X_OK):
                return portable
        except Exception as e:
            logger.warning(f"Failed to auto-restore Thorium: {e}")

    return None


SAMPLE_COMMENTS = [
    "Sangat bermanfaat, terima kasih infonya!",
    "Penjelasan yang sangat jelas dan mudah dipahami.",
    "Luar biasa, konten yang sangat menginspirasi.",
    "Terima kasih atas ilmunya, sukses selalu channelnya!",
    "Keren banget pembahasannya, ditunggu video berikutnya!",
    "Materi yang sangat bagus dan berbobot.",
    "Mantap sekali ulasannya, sangat membantu!",
    "Semoga berkah dan terus berkembang channel ini.",
    "Menarik sekali, langsung saya coba tipsnya.",
    "Konten berkualitas tinggi seperti ini yang dicari."
]


async def run_task(task_config: dict):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed! Run: pip install playwright && playwright install chromium")
        return

    ttype = task_config.get("type")
    url = task_config.get("url")
    keyword = task_config.get("keyword", "")
    target_channel = task_config.get("channel", "")
    duration_min = task_config.get("duration_min", 300)
    duration_max = task_config.get("duration_max", 600)

    logger.info(f"Starting YouTube Task: Type={ttype}, Keyword='{keyword}', Channel='{target_channel}'")

    os.makedirs(PROFILE_DIR, exist_ok=True)

    has_bridge = ensure_proxy_bridge_running()
    has_display = ensure_virtual_display()
    is_headless = not has_display

    if has_display:
        logger.info("🖥️ Virtual display aktif (:99) - Meluncurkan Chromium dalam mode GUI penuh (headless=False) untuk dukungan 100% ekstensi!")
    else:
        logger.info("Meluncurkan Chromium dalam mode headless (Xvfb belum terpasang).")

    async with async_playwright() as p:
        args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--mute-audio",
            "--disable-gpu",
            "--renderer-process-limit=4",
            "--disable-default-apps",
            "--disable-sync",
            "--no-first-run"
        ]

        launch_kwargs = {
            "user_data_dir": PROFILE_DIR,
            "headless": is_headless,
            "ignore_https_errors": True,
            "ignore_default_args": ["--enable-automation"],
            "viewport": {"width": 1366, "height": 768},
            "locale": "en-US",
            "timezone_id": "UTC",
            "args": args
        }

        # Load all installed extensions into Chromium
        ext_paths = get_installed_extension_paths()
        if ext_paths:
            ext_arg = ",".join(ext_paths)
            args.append(f"--disable-extensions-except={ext_arg}")
            args.append(f"--load-extension={ext_arg}")
            logger.info(f"Loaded {len(ext_paths)} extensions into Chromium: {[os.path.basename(os.path.dirname(p)) for p in ext_paths]}")

        system_browser = find_system_browser()
        if system_browser:
            launch_kwargs["executable_path"] = system_browser
            logger.info(f"🌐 Menggunakan browser sistem asli: {system_browser}")
        else:
            logger.info("Menggunakan browser Chromium bawaan Playwright.")

        # If proxy bridge is active, route unauthenticated traffic through local bridge
        if has_bridge:
            bridge_url = f"http://127.0.0.1:{BRIDGE_PORT}"
            launch_kwargs["proxy"] = {"server": bridge_url}

        logger.info("Launching Chromium persistent context...")
        browser = await p.chromium.launch_persistent_context(**launch_kwargs)

        # Apply Playwright-Stealth Anti-Detection Engine
        if HAS_STEALTH:
            try:
                stealth = Stealth(
                    navigator_platform_override="Linux x86_64",
                    webgl_vendor_override="Intel Inc.",
                    webgl_renderer_override="Intel Iris OpenGL Engine"
                )
                await stealth.apply_stealth_async(browser)
                logger.info("🛡️ Playwright-Stealth Anti-Detection Engine active.")
            except Exception as e:
                logger.warning(f"Failed to apply playwright-stealth: {e}")
        else:
            await browser.add_init_script("""
                try {
                    delete Object.getPrototypeOf(navigator).webdriver;
                } catch(e) {}
            """)

        page = browser.pages[0] if browser.pages else await browser.new_page()

        def attach_page_listeners(target_page, label="PAGE"):
            try:
                target_page.on("console", lambda m: log_activity("CONSOLE", f"[{m.type.upper()}] {m.text}"))
                target_page.on("pageerror", lambda e: log_activity("PAGE_ERR", str(e)))
                target_page.on("requestfailed", lambda req: log_activity("REQ_FAIL", f"{req.url} -> {req.failure}"))
                target_page.on("close", lambda _: log_activity("TAB_CLOSE", f"Closed: {target_page.url}"))
            except Exception:
                pass

        attach_page_listeners(page, "MAIN")

        # Capture any popups or new tabs opened by extensions automatically
        browser.on("page", lambda new_p: (
            log_activity("POPUP_TAB", f"Ekstensi membuka jendela/tab baru: {new_p.url}"),
            attach_page_listeners(new_p, "POPUP")
        ))

        def get_primary_web_page():
            """Returns the main web page, skipping internal extension or error pages."""
            for p in reversed(browser.pages):
                u = p.url or ""
                if u and not u.startswith("chrome://") and not u.startswith("chrome-extension://") and not u.startswith("chrome-error://"):
                    return p
            return page

        try:
            if ttype == "DIRECT_URL" and url:
                logger.info(f"Navigating directly to: {url}")
                status_code = "200"
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    if resp:
                        status_code = str(resp.status)
                except Exception as nav_err:
                    logger.warning(f"Navigation notice: {nav_err}")
                    log_activity("NAV_NOTICE", f"{url} -> {str(nav_err)[:150]}")

                # Give Single Page Apps (React/Vue/AWS Cognito) time to download JS bundle and render UI
                try:
                    await page.wait_for_selector('input, button, form, [role="main"], h1', timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(5)

                primary_page = get_primary_web_page()
                title = await primary_page.title()
                if not title:
                    await asyncio.sleep(2)
                    title = await primary_page.title()

                screenshot_file = os.path.expanduser("~/workspace/last_screenshot.png")
                try:
                    await primary_page.screenshot(path=screenshot_file, full_page=False)
                    logger.info(f"📸 Tangkapan layar tersimpan di {screenshot_file}")
                except Exception as ss_err:
                    logger.warning(f"Gagal simpan screenshot: {ss_err}")

                logger.info(f"✅ Halaman Sukses Dimuat! Judul: '{title}' | Status HTTP: {status_code}")

                # Save real-time verification log for Dashboard
                status_file = os.path.expanduser("~/workspace/browser_status.json")
                try:
                    with open(status_file, "w") as sf:
                        json.dump({
                            "url": primary_page.url,
                            "target_url": url,
                            "title": title,
                            "http_status": status_code,
                            "extensions_loaded": len(ext_paths) if ext_paths else 0,
                            "gui_mode": "Xvfb GUI (headless=False)" if has_display else "Headless",
                            "time": time.strftime("%Y-%m-%d %H:%M:%S")
                        }, sf)
                except Exception as ef:
                    logger.warning(f"Gagal simpan browser_status: {ef}")

                log_activity("STATUS", f"Halaman dimuat: '{title}' (URL: {primary_page.url}) dengan {len(ext_paths) if ext_paths else 0} ekstensi aktif [{'GUI' if has_display else 'Headless'}]. Memulai mode 24/7 non-stop.")

                # Mode 24/7 Non-Stop: Browser tetap hidup selamanya bersama seluruh ekstensi
                logger.info("🚀 Chromium 24/7 aktif berjalan tanpa batas waktu...")
                while True:
                    await asyncio.sleep(5)
                    try:
                        active_p = get_primary_web_page()
                        await active_p.screenshot(path=screenshot_file, full_page=False)
                        curr_title = await active_p.title()
                        with open(status_file, "w") as sf:
                            json.dump({
                                "url": active_p.url,
                                "title": curr_title,
                                "http_status": "200 (Running 24/7)",
                                "extensions_loaded": len(ext_paths) if ext_paths else 0,
                                "gui_mode": "Xvfb GUI (headless=False)" if has_display else "Headless",
                                "time": time.strftime("%Y-%m-%d %H:%M:%S")
                            }, sf)
                    except Exception:
                        pass

            else:
                # 1. Open YouTube
                logger.info("Opening YouTube...")
                await page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(random.uniform(2.0, 4.0))

                # Handle cookie consent if present
                try:
                    consent_btn = page.locator('button[aria-label*="Accept"], button[aria-label*="Agree"], button:has-text("Accept all")')
                    if await consent_btn.count() > 0:
                        await consent_btn.first.click()
                        await asyncio.sleep(1.0)
                except Exception:
                    pass

                # 2. Search for Keyword
                if keyword:
                    logger.info(f"Searching for: '{keyword}'")
                    search_box = page.locator('input#search, input[name="search_query"]')
                    await search_box.first.click()
                    await search_box.first.fill(keyword)
                    await page.keyboard.press("Enter")
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(random.uniform(3.0, 5.0))

                # 3. Click video matching target channel or first video
                logger.info("Selecting video to watch...")
                video_clicked = False

                if target_channel:
                    channel_videos = page.locator(f'ytd-video-renderer:has-text("{target_channel}") a#video-title')
                    if await channel_videos.count() > 0:
                        logger.info(f"Found video matching channel '{target_channel}'")
                        await channel_videos.first.click()
                        video_clicked = True

                if not video_clicked:
                    videos = page.locator('ytd-video-renderer a#video-title, ytd-rich-item-renderer a#video-title')
                    if await videos.count() > 0:
                        idx = min(random.randint(0, 2), await videos.count() - 1)
                        await videos.nth(idx).click()
                        video_clicked = True

                if not video_clicked:
                    logger.warning("No video found to click.")
                    return

                # 4. Watch duration (5-10 minutes with periodic scrolls)
                watch_time = random.randint(duration_min, duration_max)
                logger.info(f"Watching video for {watch_time} seconds (~{watch_time//60} mins)...")

                elapsed = 0
                while elapsed < watch_time:
                    chunk = min(30, watch_time - elapsed)
                    await asyncio.sleep(chunk)
                    elapsed += chunk

                    # Random natural actions
                    if random.random() < 0.3:
                        scroll_amount = random.randint(200, 500)
                        await page.mouse.wheel(0, scroll_amount)
                        await asyncio.sleep(2.0)
                        await page.mouse.wheel(0, -scroll_amount)

                # 5. Natural interaction: Like
                try:
                    like_btn = page.locator('like-button-view-model button, ytd-like-button-renderer button')
                    if await like_btn.count() > 0:
                        await like_btn.first.click()
                        logger.info("Liked video successfully.")
                except Exception:
                    pass

                # 6. Natural interaction: Comment
                try:
                    comment_box = page.locator('#placeholder-area, #simplebox-placeholder')
                    if await comment_box.count() > 0:
                        await comment_box.first.click()
                        await asyncio.sleep(1.0)
                        input_area = page.locator('#contenteditable-root')
                        comment_text = random.choice(SAMPLE_COMMENTS)
                        await input_area.fill(comment_text)
                        submit_btn = page.locator('#submit-button button')
                        await submit_btn.click()
                        logger.info(f"Commented: '{comment_text}'")
                except Exception:
                    pass

                logger.info("YouTube watch task completed successfully.")

        finally:
            await browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cfg = json.loads(sys.argv[1])
        asyncio.run(run_task(cfg))
    else:
        # Test task
        asyncio.run(run_task({"type": "SEARCH", "keyword": "Tutorial Linux", "duration_min": 60, "duration_max": 90}))
