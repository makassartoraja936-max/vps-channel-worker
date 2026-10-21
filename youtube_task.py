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
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("YouTubeWorker")


def get_system_proxy():
    """Detects and parses system egress proxy (Meta VPS runtime proxy)."""
    raw_proxy = (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or
        os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or
        os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
    )
    if not raw_proxy:
        return None
    try:
        if "://" not in raw_proxy:
            raw_proxy = f"http://{raw_proxy}"
        p = urlparse(raw_proxy)
        server_str = f"{p.scheme}://{p.hostname}"
        if p.port:
            server_str += f":{p.port}"
        
        cfg = {"server": server_str}
        if p.username:
            cfg["username"] = p.username
        if p.password:
            cfg["password"] = p.password
        logger.info(f"Using runtime egress proxy: {server_str} (Authenticated: {bool(p.username)})")
        return cfg
    except Exception as e:
        logger.warning(f"Failed to parse runtime proxy '{raw_proxy}': {e}")
        return None
logger = logging.getLogger("YouTubeWorker")

PROFILE_DIR = os.path.expanduser("~/workspace/browser_profile")

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

    env_proxy = get_system_proxy()

    async with async_playwright() as p:
        launch_kwargs = {
            "user_data_dir": PROFILE_DIR,
            "headless": True,
            "ignore_https_errors": True,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--mute-audio"
            ]
        }
        if env_proxy:
            launch_kwargs["proxy"] = env_proxy

        browser = await p.chromium.launch_persistent_context(**launch_kwargs)

        page = await browser.new_page()

        try:
            if ttype == "DIRECT_URL" and url:
                logger.info(f"Navigating directly to: {url}")
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                title = await page.title()
                status_code = resp.status if resp else "200"
                screenshot_file = os.path.expanduser("~/workspace/last_screenshot.png")
                try:
                    await page.screenshot(path=screenshot_file)
                except Exception:
                    pass
                logger.info(f"✅ Halaman Sukses Dimuat! Judul: '{title}' | Status HTTP: {status_code}")
                # Keep open naturally for 1 to 3 minutes
                await asyncio.sleep(random.randint(60, 180))

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
