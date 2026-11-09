"""
Playwright Network Interception Engine for Ultra-Dense Corridors in Ibb.
"""

import asyncio
import json
import re
import math
from typing import Dict, List, Any, Optional
from playwright.async_api import async_playwright, Response
from config import DEFAULT_USER_AGENT, SOCS_COOKIE


class MicroPanningNetworkInterceptor:
    def __init__(self, headless: bool = True, lang: str = "ar", gl: str = "ye"):
        self.headless = headless
        self.lang = lang
        self.gl = gl
        self.captured_places: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()

    def _clean_google_rpc_response(self, text: str) -> Optional[Any]:
        try:
            if text.startswith(")]}'"):
                text = text[4:].strip()
            elif text.startswith("/*-secure-"):
                text = re.sub(r"^/\*-secure-[^\n]*\n", "", text)
            return json.loads(text)
        except Exception:
            return None

    def _extract_entities_from_raw_payload(self, data: Any) -> List[Dict[str, Any]]:
        results = []

        def recurse(node):
            if isinstance(node, list):
                place_id = None
                title = None
                coords = None

                for item in node:
                    if isinstance(item, str):
                        if item.startswith("ChIJ") and len(item) >= 20:
                            place_id = item
                        elif place_id is None and item.startswith("0x") and ":" in item:
                            place_id = item
                    elif isinstance(item, list) and len(item) == 2:
                        if (isinstance(item[0], (int, float)) and isinstance(item[1], (int, float))
                                and 13.0 < item[0] < 15.0 and 43.0 < item[1] < 45.0):
                            coords = (item[0], item[1])

                if place_id:
                    strings = [x for x in node if isinstance(x, str) and not x.startswith("http") and len(x) > 1]
                    if strings:
                        clean_strs = [s for s in strings if s != place_id and not s.startswith("ChI")]
                        if clean_strs:
                            title = clean_strs[0]

                    if title and coords:
                        results.append({
                            "place_id": place_id,
                            "title": title,
                            "lat": coords[0],
                            "lng": coords[1],
                            "source_tier": "tier3_playwright_interceptor"
                        })

                for sub in node:
                    recurse(sub)
            elif isinstance(node, dict):
                for v in node.values():
                    recurse(v)

        recurse(data)
        return results

    async def _on_response_intercept(self, response: Response):
        url = response.url
        if ("/search?tbm=map" in url or
            "/maps/rpc/search" in url or
            "/maps/preview/place" in url or
            "search?authuser" in url):
            try:
                text = await response.text()
                parsed = self._clean_google_rpc_response(text)
                if parsed:
                    entities = self._extract_entities_from_raw_payload(parsed)
                    async with self.lock:
                        for ent in entities:
                            pid = ent["place_id"]
                            if pid not in self.captured_places:
                                self.captured_places[pid] = ent
                                print(f"  [Sniffer] Intercepted raw pin: {ent.get('title')} ({ent.get('lat')}, {ent.get('lng')})")
            except Exception:
                pass

    async def scan_corridor_with_panning(
        self,
        start_lat: float,
        start_lng: float,
        end_lat: float,
        end_lng: float,
        keyword: str = "",
        zoom: int = 21,
        step_deg: float = 0.00035
    ) -> List[Dict[str, Any]]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                ]
            )

            context = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                locale=f"{self.lang}-{self.gl.upper()}",
                viewport={"width": 1440, "height": 900},
                geolocation={"latitude": start_lat, "longitude": start_lng, "accuracy": 10},
                permissions=["geolocation"],
            )

            await context.add_cookies([
                {
                    "name": "SOCS",
                    "value": SOCS_COOKIE,
                    "domain": ".google.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                }
            ])

            page = await context.new_page()
            page.on("response", self._on_response_intercept)

            base_url = f"https://www.google.com/maps/@{start_lat:.6f},{start_lng:.6f},{zoom}z?hl={self.lang}&gl={self.gl}"
            print(f"[Playwright] Opening Google Maps at {base_url} (Zoom {zoom})...")

            try:
                await page.goto(base_url, wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                print(f"[Playwright] Navigation warning: {e}")

            await page.wait_for_timeout(2000)

            if keyword:
                try:
                    search_box = page.locator("#searchboxinput")
                    if await search_box.is_visible():
                        await search_box.fill(keyword)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(3000)
                except Exception:
                    pass

            delta_lat = end_lat - start_lat
            delta_lng = end_lng - start_lng
            distance = math.sqrt(delta_lat**2 + delta_lng**2)

            steps = max(1, int(distance / step_deg))
            step_lat = delta_lat / steps
            step_lng = delta_lng / steps

            print(f"[Playwright] Starting micro-panning across {steps} camera steps (step={step_deg}°)...")

            center_x, center_y = 720, 450

            for i in range(steps):
                await page.mouse.move(center_x, center_y)
                await page.mouse.down()
                drag_x = center_x - int(50 * (step_lng / (abs(step_lng) + 1e-9)))
                drag_y = center_y + int(50 * (step_lat / (abs(step_lat) + 1e-9)))
                await page.mouse.move(drag_x, drag_y, steps=4)
                await page.mouse.up()

                await page.keyboard.press("ArrowRight")
                await page.wait_for_timeout(600)

            await page.wait_for_timeout(1500)
            await browser.close()

        return list(self.captured_places.values())
