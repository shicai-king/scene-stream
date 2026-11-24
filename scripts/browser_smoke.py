"""Real browser verification against a running service (Mock or Scope)."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time

from playwright.async_api import async_playwright


async def run(args):
    results = {"url": args.url, "checks": [], "browser_errors": []}
    async with async_playwright() as playwright:
        launch = {"headless": True}
        if args.browser:
            launch["executable_path"] = args.browser
        browser = await playwright.chromium.launch(**launch)
        context = await browser.new_context(viewport={"width": 1440, "height": 980}, device_scale_factor=1)
        page, other = await context.new_page(), await context.new_page()
        for target in (page, other):
            target.on("pageerror", lambda error: results["browser_errors"].append(str(error)))
            await target.goto(args.url)
            await target.wait_for_function("Number(document.querySelector('#video-canvas').dataset.renderedFrames) >= 3", timeout=args.timeout * 1000)
        results["checks"].append("two browsers decode live frames")
        room_id = await page.locator("#video-canvas").get_attribute("data-room-id")
        assert room_id == await other.locator("#video-canvas").get_attribute("data-room-id")
        cap = await (await context.request.get(args.url + "/api/v1/capacity")).json()
        results["capacity"] = cap
        assert cap["active_sessions"] >= 1
        text = "A red fox walks through a snowy forest, cinematic tracking shot."
        await page.locator("#prompt-input").fill(text)
        await page.locator("#send-prompt").click()
        await other.locator(".chat-message p").filter(has_text=text).last.wait_for()
        await other.locator(".message-status.sent").last.wait_for(timeout=10000)
        results["checks"].append("prompt broadcast and server delivery status reach both viewers")
        room_buttons = page.locator(".room-item")
        if await room_buttons.count() > 1:
            previous = await other.locator("#video-canvas").get_attribute("data-frame-seq")
            await room_buttons.nth(1).click()
            await page.wait_for_function("document.querySelector('#video-canvas').dataset.roomId !== " + json.dumps(room_id) + " && Number(document.querySelector('#video-canvas').dataset.renderedFrames) >= 3")
            await other.wait_for_function("Number(document.querySelector('#video-canvas').dataset.frameSeq) > " + str(previous))
            assert await page.locator(".chat-message p").filter(has_text=text).count() == 0
            results["checks"].append("room switch isolates messages and preserves other viewer generation")
            await page.locator(".room-item").first.click()
            await page.wait_for_function("document.querySelector('#video-canvas').dataset.roomId === " + json.dumps(room_id))
        assert await page.locator("#stage-placeholder").is_hidden()
        assert not results["browser_errors"], results["browser_errors"]
        Path(args.output).mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(Path(args.output) / "desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.screenshot(path=str(Path(args.output) / "mobile.png"), full_page=True)
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile horizontal overflow"
        results["checks"].append("desktop/mobile rendering and no JavaScript errors")
        results["passed"] = True
        Path(args.output, "browser-report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(results, ensure_ascii=False, indent=2))
        await browser.close()


parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8080")
parser.add_argument("--browser", default=os.getenv("CHROMIUM_EXECUTABLE"))
parser.add_argument("--timeout", type=int, default=120)
parser.add_argument("--output", default="artifacts/browser")
asyncio.run(run(parser.parse_args()))
