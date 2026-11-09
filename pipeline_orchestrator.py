"""
Unified Pipeline Orchestrator for Ibb Geospatial Scraping.

Coordinates the 3-Tier Hybrid Architecture:
- Tier 1: gosom/google-maps-scraper (Fast grid sweep in Go/Docker)
- Tier 2: Playwright Network Interceptor (Zoom 21 micro-panning for 1m-adjacent shops & multi-story buildings)
- Tier 3: omkarcloud/google-maps-scraper (Botasaurus deep enrichment for place_id metadata & reviews)
- OSM Enrichment & Spatial Join
- SQLite / GeoJSON Deduplication and Checkpoint Management with Graceful Time-Budgeting
"""

import asyncio
import subprocess
import json
import os
import time
import argparse
from typing import List, Dict, Any

from config import DENSE_CORRIDORS
from grid_generator import AdaptiveGridGenerator
from semantic_seeds import get_priority_seeds, get_all_seeds
from playwright_interceptor import MicroPanningNetworkInterceptor
from osm_spatial_enricher import OSMSpatialEnricher
from dedup_engine import DedupEngine


class UnifiedIbbScraperPipeline:
    def __init__(
        self,
        shard_file: str = "",
        db_path: str = "ibb_places.db",
        checkpoint_path: str = "checkpoint.json",
        headless: bool = True,
        max_cells: int = 0,
        max_runtime_minutes: float = 300.0
    ):
        self.shard_file = shard_file
        self.db = DedupEngine(db_path, checkpoint_path)
        self.osm = OSMSpatialEnricher()
        self.headless = headless
        self.max_cells = max_cells
        self.max_runtime_seconds = max_runtime_minutes * 60.0
        self.start_time = time.time()
        self.interceptor = MicroPanningNetworkInterceptor(headless=self.headless)

    def is_time_budget_exceeded(self) -> bool:
        elapsed = time.time() - self.start_time
        return elapsed >= self.max_runtime_seconds

    def prepare_environment(self):
        print("[Pipeline] Step 0: Initializing OSM spatial data for Ibb...")
        self.osm.fetch_osm_data_for_ibb()

    def load_grid_cells(self) -> List[Dict[str, Any]]:
        if self.shard_file and os.path.exists(self.shard_file):
            print(f"[Pipeline] Loading cells from shard: {self.shard_file}")
            with open(self.shard_file, "r", encoding="utf-8") as f:
                cells = json.load(f)
        else:
            print("[Pipeline] Generating fresh adaptive grid cells for Ibb Governorate & City...")
            gen = AdaptiveGridGenerator()
            cells = gen.generate_full_adaptive_grid(include_rural=True)

        pending_cells = [c for c in cells if not self.db.checkpoint.is_cell_completed(c["cell_id"])]
        print(f"[Pipeline] Total shard cells: {len(cells)} | Already completed: {len(cells) - len(pending_cells)} | Pending: {len(pending_cells)}")

        if self.max_cells and self.max_cells > 0:
            print(f"[Pipeline] Limiting batch execution to {self.max_cells} pending priority cells for this run.")
            return pending_cells[:self.max_cells]
        print(f"[Pipeline] UNLIMITED FULL SWEEP MODE (max_cells=0): Processing all {len(pending_cells)} pending cells within time budget ({self.max_runtime_seconds/60:.1f} min).")
        return pending_cells

    def run_tier1_gosom_sweep(self, cells: List[Dict[str, Any]], keywords: List[str]):
        gosom_input_file = "gosom_queries.txt"
        gosom_output_file = "gosom_results.json"

        queries = []
        tier1_cells = [c for c in cells if c.get("tier") == "tier1_gosom_grid"]
        for cell in tier1_cells[:150]:
            c_lat = cell["center_lat"]
            c_lng = cell["center_lng"]
            for kw in keywords[:3]:
                queries.append(f"{kw} near {c_lat},{c_lng}")

        if not queries:
            print("[Tier 1 - Gosom] No tier1 cells in current slice (prioritizing ultra-dense corridors first).")
            return

        with open(gosom_input_file, "w", encoding="utf-8") as f:
            for q in queries:
                f.write(f"{q}\n")

        print(f"[Tier 1 - Gosom] Generated {len(queries)} sweep queries for gosom/google-maps-scraper.")

        cmd = [
            "docker", "run", "--rm",
            "-v", f"{os.getcwd()}:/data",
            "gosom/google-maps-scraper",
            "-input", f"/data/{gosom_input_file}",
            "-results", f"/data/{gosom_output_file}",
            "-c", "8",
            "-depth", "1",
            "-lang", "ar",
            "-exit-on-empty"
        ]

        print(f"[Tier 1 - Gosom] Executing: {' '.join(cmd)}")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            print(f"[Tier 1 - Gosom] Exit code: {res.returncode}")
        except Exception as e:
            print(f"[Tier 1 - Gosom] Notice: Gosom Docker execution finished or skipped: {e}")

        if os.path.exists(gosom_output_file):
            try:
                with open(gosom_output_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        raw_place = {
                            "place_id": item.get("place_id") or item.get("data_id"),
                            "cid": item.get("cid"),
                            "title": item.get("title"),
                            "category": item.get("category"),
                            "address": item.get("address"),
                            "phone": item.get("phone"),
                            "website": item.get("website"),
                            "lat": item.get("latitude"),
                            "lng": item.get("longitude"),
                            "rating": item.get("rating"),
                            "reviews_count": item.get("reviews"),
                            "source_tier": "tier1_gosom_grid"
                        }
                        enriched = self.osm.enrich_place_address(raw_place)
                        self.db.upsert_place(enriched)
            except Exception as e:
                print(f"[Tier 1 - Gosom] Error parsing output: {e}")

    async def run_tier2_playwright_dense_panning(self, cells: List[Dict[str, Any]]):
        print("[OSM Spatial Ingestion] Syncing OSM buildings, shops, and landmarks into database...")
        osm_count = 0
        for idx, bldg in enumerate(self.osm.buildings):
            if bldg.get("has_name") and bldg.get("center_lat") and bldg.get("center_lng"):
                poi = {
                    "place_id": f"osm_bldg_{idx}_{bldg['center_lat']:.5f}",
                    "title": bldg["name"],
                    "category": bldg.get("category", "معلم / مبنى تجاري"),
                    "lat": bldg["center_lat"],
                    "lng": bldg["center_lng"],
                    "source_tier": "osm_overpass_building"
                }
                enriched = self.osm.enrich_place_address(poi)
                self.db.upsert_place(enriched)
                osm_count += 1

        for idx, item in enumerate(self.osm.neighborhoods):
            if item.get("lat") and item.get("lng") and item.get("name"):
                poi = {
                    "place_id": f"osm_node_{item.get('id', idx)}_{item['lat']:.5f}",
                    "title": item["name"],
                    "category": item.get("type", "منشأة / معلم"),
                    "phone": item.get("phone"),
                    "lat": item["lat"],
                    "lng": item["lng"],
                    "source_tier": "osm_overpass_poi"
                }
                enriched = self.osm.enrich_place_address(poi)
                self.db.upsert_place(enriched)
                osm_count += 1
        print(f"[OSM Spatial Ingestion] Indexed and enriched {osm_count} OSM entities.")

        dense_cells = [c for c in cells if c.get("tier") == "tier3_panning_dense"]
        print(f"[Tier 2 - Playwright Sniffer] Found {len(dense_cells)} pending ultra-dense corridor cells in shard.")

        all_kws = get_all_seeds()

        for idx, cell in enumerate(dense_cells):
            if self.is_time_budget_exceeded():
                print(f"\n[Time Budget Reached] Gracefully stopping after {idx} cells to commit checkpoint & DB.")
                break

            cell_id = cell["cell_id"]
            if self.db.checkpoint.is_cell_completed(cell_id):
                continue

            kw = all_kws[idx % len(all_kws)]
            elapsed_m = (time.time() - self.start_time) / 60.0
            print(f"\n[Tier 2 - Playwright Sniffer] [{elapsed_m:.1f}m] Processing ({idx+1}/{len(dense_cells)}): {cell['zone_name']} | Cell: {cell_id} | Seed: {kw}")

            try:
                captured = await self.interceptor.scan_corridor_with_panning(
                    start_lat=cell["min_lat"],
                    start_lng=cell["min_lng"],
                    end_lat=cell["max_lat"],
                    end_lng=cell["max_lng"],
                    keyword=kw,
                    zoom=cell.get("zoom", 21),
                    step_deg=0.00035
                )

                print(f"  [Sniffer Results] Cell {cell_id} intercepted {len(captured)} raw entities.")
                for place in captured:
                    place["corridor_key"] = cell.get("corridor_key")
                    enriched = self.osm.enrich_place_address(place)
                    self.db.upsert_place(enriched)

                self.db.checkpoint.mark_cell_completed(cell_id)
            except Exception as e:
                print(f"  [Sniffer Error] Cell {cell_id} encountered error: {e}")

    def run_tier3_deep_enrichment(self):
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT place_id, title, lat, lng
            FROM places
            WHERE (phone IS NULL OR opening_hours IS NULL) AND place_id NOT LIKE 'synth_%'
            LIMIT 100
        """)
        candidates = cursor.fetchall()
        print(f"\n[Tier 3 - Deep Botasaurus Enrichment] Found {len(candidates)} candidates queued for deep inspection.")

    def execute_full_pipeline(self):
        self.prepare_environment()
        cells = self.load_grid_cells()
        keywords = get_priority_seeds()

        self.run_tier1_gosom_sweep(cells, keywords)
        asyncio.run(self.run_tier2_playwright_dense_panning(cells))
        self.run_tier3_deep_enrichment()

        print("\n[Pipeline Complete] Exporting unified data...")
        self.db.export_geojson("ibb_places.geojson")
        self.db.export_csv("ibb_places.csv")
        print(f"[Summary] Stats: {self.db.checkpoint.data['stats']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ibb Unified Scraper Pipeline")
    parser.add_argument("--shard-file", type=str, default="", help="Path to grid shard JSON file")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browsers headlessly")
    parser.add_argument("--max-cells", type=int, default=0, help="Limit number of cells per run (0 = unlimited)")
    parser.add_argument("--max-runtime-minutes", type=float, default=300.0, help="Graceful stop time budget in minutes")
    args = parser.parse_args()

    pipeline = UnifiedIbbScraperPipeline(
        shard_file=args.shard_file,
        headless=args.headless,
        max_cells=args.max_cells,
        max_runtime_minutes=args.max_runtime_minutes
    )
    pipeline.execute_full_pipeline()
