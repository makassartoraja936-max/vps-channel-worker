import asyncio
import os
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser_bin = os.path.expanduser("~/workspace/thorium/opt/chromium.org/thorium/thorium")
        if not os.path.exists(browser_bin):
            for c in ["/usr/bin/thorium-browser", "/opt/chromium.org/thorium/thorium", "/usr/bin/google-chrome-stable", "/usr/bin/chromium-browser"]:
                if os.path.exists(c):
                    browser_bin = c
                    break

        print(f"Menguji biner: {browser_bin}")
        ctx = await p.chromium.launch_persistent_context(
            "/tmp/test_pw_thorium",
            executable_path=browser_bin,
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1366,768"
            ]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://studiolab.sagemaker.aws/login", wait_until="domcontentloaded")
        title = await page.title()
        print(f"SUCCESS_THORIUM_PW_TITLE: '{title}'")
        ss_path = os.path.expanduser("~/workspace/last_screenshot.png")
        await page.screenshot(path=ss_path, full_page=False)
        print(f"SCREENSHOT_SAVED_BYTES: {os.path.getsize(ss_path)}")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(test())
