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
import sys
import time
from urllib.parse import urlparse

import socket
import subprocess

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
    """Scans user profile directory for installed unpacked extensions."""
    ext_base = os.path.join(PROFILE_DIR, "Default", "Extensions")
    if not os.path.exists(ext_base):
        return []
    paths = []
    try:
        for ext_id in os.listdir(ext_base):
            ext_folder = os.path.join(ext_base, ext_id)
            if os.path.isdir(ext_folder):
                for v in os.listdir(ext_folder):
                    v_path = os.path.join(ext_folder, v)
                    if os.path.isdir(v_path) and os.path.exists(os.path.join(v_path, "manifest.json")):
                        paths.append(v_path)
    except Exception as e:
        logger.warning(f"Error scanning extensions: {e}")
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

    async with async_playwright() as p:
        args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--mute-audio",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--renderer-process-limit=2",
            "--js-flags=--max-old-space-size=256",
            "--disable-default-apps",
            "--disable-sync",
            "--no-first-run",
            # Cloudflare Fast DNS over HTTPS (1.1.1.1) to eliminate DNS resolution timeouts
            "--enable-features=DnsOverHttps",
            "--dns-over-https-mode=automatic",
            "--dns-over-https-templates=https://1.1.1.1/dns-query"
        ]

        # Realistic Human Desktop Chrome User-Agent & Headers (Bypasses AWS CloudFront 403)
        human_user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )
        standard_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

        launch_kwargs = {
            "user_data_dir": PROFILE_DIR,
            "headless": True,
            "ignore_https_errors": True,
            "user_agent": human_user_agent,
            "viewport": {"width": 1366, "height": 768},
            "locale": "en-US",
            "timezone_id": "UTC",
            "extra_http_headers": standard_headers,
            "args": args
        }

        # Load all installed extensions into Chromium
        ext_paths = get_installed_extension_paths()
        if ext_paths:
            ext_arg = ",".join(ext_paths)
            args.append(f"--disable-extensions-except={ext_arg}")
            args.append(f"--load-extension={ext_arg}")
            logger.info(f"Loaded {len(ext_paths)} extensions into Chromium: {[os.path.basename(os.path.dirname(p)) for p in ext_paths]}")

        # If proxy bridge is active, route unauthenticated traffic through local bridge
        if has_bridge:
            bridge_url = f"http://127.0.0.1:{BRIDGE_PORT}"
            launch_kwargs["proxy"] = {"server": bridge_url}
            args.append(f"--proxy-server={bridge_url}")
            logger.info(f"Routing browser through unauthenticated local bridge: {bridge_url}")

        browser = await p.chromium.launch_persistent_context(**launch_kwargs)

        # Anti-Detection Stealth Script (Deletes navigator.webdriver & fakes plugins)
        await browser.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)

        page = browser.pages[0] if browser.pages else await browser.new_page()

        def attach_page_listeners(target_page, label="PAGE"):
            try:
                target_page.on("console", lambda m: log_activity("CONSOLE", f"[{m.type.upper()}] {m.text}"))
                target_page.on("pageerror", lambda e: log_activity("PAGE_ERR", str(e)))
                target_page.on("close", lambda _: log_activity("TAB_CLOSE", f"Closed: {target_page.url}"))
            except Exception:
                pass

        attach_page_listeners(page, "MAIN")

        # Capture any popups or new tabs opened by extensions automatically
        browser.on("page", lambda new_p: (
            log_activity("POPUP_TAB", f"Ekstensi membuka jendela/tab baru: {new_p.url}"),
            attach_page_listeners(new_p, "POPUP")
        ))

        try:
            if ttype == "DIRECT_URL" and url:
                logger.info(f"Navigating directly to: {url}")
                status_code = "200"
                try:
                    resp = await page.goto(url, wait_until="load", timeout=45000)
                    if resp:
                        status_code = str(resp.status)
                except Exception as nav_err:
                    logger.warning(f"Navigation notice (continuing to render): {nav_err}")

                # Give Single Page Apps (React/Vue/AWS) time to download JS bundle and render UI
                try:
                    await page.wait_for_selector('input, button, form, [role="main"], h1', timeout=6000)
                except Exception:
                    pass
                await asyncio.sleep(4)

                title = await page.title()
                screenshot_file = os.path.expanduser("~/workspace/last_screenshot.png")
                try:
                    await page.screenshot(path=screenshot_file, full_page=False)
                    logger.info(f"📸 Tangkapan layar tersimpan di {screenshot_file}")
                except Exception as ss_err:
                    logger.warning(f"Gagal simpan screenshot: {ss_err}")

                logger.info(f"✅ Halaman Sukses Dimuat! Judul: '{title}' | Status HTTP: {status_code}")

                # Save real-time verification log for Dashboard
                status_file = os.path.expanduser("~/workspace/browser_status.json")
                try:
                    with open(status_file, "w") as sf:
                        json.dump({
                            "url": url,
                            "title": title,
                            "http_status": status_code,
                            "extensions_loaded": len(ext_paths) if ext_paths else 0,
                            "time": time.strftime("%Y-%m-%d %H:%M:%S")
                        }, sf)
                except Exception as ef:
                    logger.warning(f"Gagal simpan browser_status: {ef}")

                log_activity("STATUS", f"Halaman dimuat: '{title}' (HTTP {status_code}) dengan {len(ext_paths) if ext_paths else 0} ekstensi aktif. Memulai mode 24/7 non-stop.")

                # Mode 24/7 Non-Stop: Browser tetap hidup selamanya bersama seluruh ekstensi
                logger.info("🚀 Chromium 24/7 aktif berjalan tanpa batas waktu...")
                loop_tick = 0
                while True:
                    await asyncio.sleep(15)
                    loop_tick += 1
                    # Tiap 60 detik (loop_tick % 4 == 0), segarkan tangkapan layar & file status
                    if loop_tick % 4 == 0:
                        try:
                            active_p = browser.pages[-1] if browser.pages else page
                            await active_p.screenshot(path=screenshot_file, full_page=False)
                            curr_title = await active_p.title()
                            with open(status_file, "w") as sf:
                                json.dump({
                                    "url": active_p.url,
                                    "title": curr_title,
                                    "http_status": "200 (Running 24/7)",
                                    "extensions_loaded": len(ext_paths) if ext_paths else 0,
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
