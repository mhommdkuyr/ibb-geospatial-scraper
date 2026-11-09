"""
Playwright Network Interception & DOM Extraction Engine for Ultra-Dense Corridors in Ibb.

Combines:
1. Raw Network Interception (/search?tbm=map, /maps/rpc/search, /maps/preview/place)
2. Direct search query URLs (/maps/search/<keyword>/@<lat>,<lng>,21z?hl=ar)
3. DOM Fallback extraction from Google Maps place links (/maps/place/...) and initial APP_INITIALIZATION_STATE
"""

import asyncio
import json
import re
import math
import urllib.parse
from typing import Dict, List, Any, Optional
from playwright.async_api import async_playwright, Response, Page
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
                        if item.startswith("ChIJ") and len(item) >= 18:
                            place_id = item
                        elif place_id is None and item.startswith("0x") and ":0x" in item:
                            place_id = item
                    elif isinstance(item, list) and len(item) >= 2:
                        if (len(item) == 2 and isinstance(item[0], (int, float)) and isinstance(item[1], (int, float))
                                and 13.0 < item[0] < 15.0 and 43.0 < item[1] < 45.0):
                            coords = (float(item[0]), float(item[1]))
                        elif (len(item) >= 4 and isinstance(item[2], (int, float)) and isinstance(item[3], (int, float))
                                and 13.0 < item[2] < 15.0 and 43.0 < item[3] < 45.0):
                            coords = (float(item[2]), float(item[3]))

                if place_id or coords:
                    strings = [
                        x for x in node
                        if isinstance(x, str) and not x.startswith("http") and not x.startswith("0x")
                        and not x.startswith("ChI") and len(x.strip()) > 2
                    ]
                    if strings:
                        title = strings[0].strip()

                    if title and coords:
                        pid = place_id if place_id else f"rpc_{coords[0]:.6f}_{coords[1]:.6f}"
                        results.append({
                            "place_id": pid,
                            "title": title,
                            "lat": coords[0],
                            "lng": coords[1],
                            "source_tier": "tier2_playwright_rpc_interceptor"
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
        if any(p in url for p in ("/search?tbm=map", "/maps/rpc/", "/maps/preview/place", "search?authuser", "/maps/search/")):
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
                                print(f"  [Sniffer] Intercepted RPC pin: {ent.get('title')} ({ent.get('lat')}, {ent.get('lng')})")
            except Exception:
                pass

    async def _extract_dom_and_state_places(self, page: Page, fallback_lat: float, fallback_lng: float):
        try:
            links = await page.eval_on_selector_all(
                "a[href*='/maps/place/']",
                "elements => elements.map(el => ({href: el.href, label: el.getAttribute('aria-label') || el.innerText}))"
            )
            async with self.lock:
                for item in links:
                    href = item.get("href", "")
                    label = (item.get("label") or "").strip().split("\n")[0]
                    m_coord = re.search(r"!3d(1[34]\.\d+)!4d(4[34]\.\d+)", href)
                    if not m_coord:
                        m_coord = re.search(r"@(1[34]\.\d+),(4[34]\.\d+)", href)
                    lat = float(m_coord.group(1)) if m_coord else fallback_lat
                    lng = float(m_coord.group(2)) if m_coord else fallback_lng

                    m_pid = re.search(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+|ChIJ[\w-]+)", href)
                    pid = m_pid.group(1) if m_pid else f"dom_{lat:.6f}_{lng:.6f}_{hash(label) % 10000}"

                    if label and pid not in self.captured_places:
                        self.captured_places[pid] = {
                            "place_id": pid,
                            "title": label,
                            "lat": lat,
                            "lng": lng,
                            "website": href,
                            "source_tier": "tier2_playwright_dom"
                        }
                        print(f"  [DOM Extractor] Captured place: {label} ({lat}, {lng})")

            html = await page.content()
            matches = re.findall(r'\[null,null,(13\.\d{4,8}),(44\.\d{4,8})\].{1,300}?\"([\u0600-\u06FF][\u0600-\u06FF\s\d\-]{2,50})\"', html)
            async with self.lock:
                for m in matches:
                    lat_v, lng_v, name_ar = float(m[0]), float(m[1]), m[2].strip()
                    pid = f"state_{lat_v:.6f}_{lng_v:.6f}"
                    if pid not in self.captured_places:
                        self.captured_places[pid] = {
                            "place_id": pid,
                            "title": name_ar,
                            "lat": lat_v,
                            "lng": lng_v,
                            "source_tier": "tier2_playwright_app_state"
                        }
                        print(f"  [State Extractor] Captured Arabic POI: {name_ar} ({lat_v}, {lng_v})")
        except Exception as e:
            print(f"  [Extractor Warning] {e}")

    async def scan_corridor_with_panning(
        self,
        start_lat: float,
        start_lng: float,
        end_lat: float,
        end_lng: float,
        keyword: str = "محلات تجارية وصيدليات ومطاعم",
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

            encoded_kw = urllib.parse.quote(keyword)
            search_url = f"https://www.google.com/maps/search/{encoded_kw}/@{start_lat:.6f},{start_lng:.6f},{zoom}z?hl={self.lang}&gl={self.gl}"
            print(f"[Playwright] Navigating to dense search URL: {search_url}")

            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                print(f"[Playwright] Navigation warning: {e}")

            await page.wait_for_timeout(3000)
            await self._extract_dom_and_state_places(page, start_lat, start_lng)

            delta_lat = end_lat - start_lat
            delta_lng = end_lng - start_lng
            distance = math.sqrt(delta_lat**2 + delta_lng**2)

            steps = max(1, int(distance / step_deg))
            step_lat = delta_lat / steps
            step_lng = delta_lng / steps

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

            await self._extract_dom_and_state_places(page, end_lat, end_lng)
            await browser.close()

        return list(self.captured_places.values())
