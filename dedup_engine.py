"""
Deduplication, Entity Merging & Database Engine for Ibb Geospatial Scraper.
"""

import sqlite3
import json
import os
import re
from typing import Dict, List, Any, Optional
from difflib import SequenceMatcher
import math


def haversine_dist(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def normalize_arabic_text(text: str) -> str:
    if not text:
        return ""
    tashkeel = re.compile(r"[\u064B-\u0652\u0670]")
    text = tashkeel.sub("", text)
    text = re.sub(r"[إأآٱ]", "ا", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"[^\w\s]", " ", text)
    stop_words = {"محل", "محلات", "شركة", "مؤسسة", "معرض", "دكان", "مركز", "سوق", "وكالة"}
    tokens = [w for w in text.split() if w not in stop_words]
    return " ".join(tokens).strip()


def are_titles_matching(t1: str, t2: str, dist_m: float) -> bool:
    if not t1 or not t2:
        return False
    if t1 == t2:
        return True
    if (t1 in t2 or t2 in t1) and dist_m <= 15.0:
        return True
    tokens1 = set(t1.split())
    tokens2 = set(t2.split())
    if tokens1 and tokens2:
        common = tokens1.intersection(tokens2)
        if len(common) >= 1 and (len(common) / min(len(tokens1), len(tokens2))) >= 0.65 and dist_m <= 15.0:
            return True
    similarity = SequenceMatcher(None, t1, t2).ratio()
    return similarity >= 0.75 and dist_m <= 15.0


class CheckpointManager:
    def __init__(self, checkpoint_path: str = "checkpoint.json"):
        self.path = checkpoint_path
        self.data: Dict[str, Any] = {
            "completed_cells": [],
            "completed_keywords": [],
            "stats": {"inserted": 0, "merged": 0, "total_seen": 0}
        }
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                print(f"[Checkpoint] Warning loading checkpoint: {e}")

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_cell_completed(self, cell_id: str) -> bool:
        return cell_id in self.data["completed_cells"]

    def mark_cell_completed(self, cell_id: str):
        if cell_id not in self.data["completed_cells"]:
            self.data["completed_cells"].append(cell_id)
            self.save()


class DedupEngine:
    def __init__(self, db_path: str = "ibb_places.db", checkpoint_path: str = "checkpoint.json"):
        self.db_path = db_path
        self.checkpoint = CheckpointManager(checkpoint_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS places (
                place_id TEXT PRIMARY KEY,
                cid TEXT,
                title TEXT NOT NULL,
                title_normalized TEXT,
                category TEXT,
                address TEXT,
                address_detailed TEXT,
                phone TEXT,
                website TEXT,
                rating REAL,
                reviews_count INTEGER,
                reviews_data TEXT,
                photos_data TEXT,
                opening_hours TEXT,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                osm_nearest_street TEXT,
                osm_neighborhood TEXT,
                osm_nearest_landmark TEXT,
                source_tier TEXT,
                corridor_key TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_places_cid ON places(cid);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_places_coords ON places(lat, lng);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_places_title_norm ON places(title_normalized);")
        self.conn.commit()

    def find_spatial_duplicate(self, lat: float, lng: float, title_norm: str, threshold_dist_m: float = 15.0) -> Optional[str]:
        delta_deg = 0.0002
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT place_id, lat, lng, title_normalized
            FROM places
            WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?
        """, (lat - delta_deg, lat + delta_deg, lng - delta_deg, lng + delta_deg))

        rows = cursor.fetchall()
        for row in rows:
            dist = haversine_dist(lat, lng, row["lat"], row["lng"])
            if dist <= threshold_dist_m:
                cand_title = row["title_normalized"] or ""
                if are_titles_matching(title_norm, cand_title, dist):
                    return row["place_id"]
        return None

    def upsert_place(self, place: Dict[str, Any]) -> str:
        place_id = place.get("place_id")
        title = place.get("title", "").strip()
        lat = place.get("lat")
        lng = place.get("lng")

        if not title or not lat or not lng:
            return "skipped_invalid"

        title_norm = normalize_arabic_text(title)
        self.checkpoint.data["stats"]["total_seen"] += 1

        cursor = self.conn.cursor()

        existing_id = None
        if place_id:
            cursor.execute("SELECT place_id FROM places WHERE place_id = ?", (place_id,))
            row = cursor.fetchone()
            if row:
                existing_id = row["place_id"]

        if not existing_id:
            existing_id = self.find_spatial_duplicate(lat, lng, title_norm)

        if existing_id:
            cursor.execute("SELECT * FROM places WHERE place_id = ?", (existing_id,))
            curr = dict(cursor.fetchone())

            phone = place.get("phone") or curr.get("phone")
            website = place.get("website") or curr.get("website")
            category = place.get("category") or curr.get("category")
            address_detailed = place.get("address_detailed") or curr.get("address_detailed")
            hours = json.dumps(place["opening_hours"], ensure_ascii=False) if place.get("opening_hours") else curr.get("opening_hours")
            reviews_data = json.dumps(place["reviews_data"], ensure_ascii=False) if place.get("reviews_data") else curr.get("reviews_data")
            photos_data = json.dumps(place["photos_data"], ensure_ascii=False) if place.get("photos_data") else curr.get("photos_data")
            rating = place.get("rating") if place.get("rating") is not None else curr.get("rating")
            reviews_count = place.get("reviews_count") if place.get("reviews_count") is not None else curr.get("reviews_count")

            cursor.execute("""
                UPDATE places SET
                    phone = ?, website = ?, category = ?, address_detailed = ?,
                    opening_hours = ?, reviews_data = ?, photos_data = ?,
                    rating = ?, reviews_count = ?, updated_at = CURRENT_TIMESTAMP
                WHERE place_id = ?
            """, (phone, website, category, address_detailed, hours, reviews_data, photos_data, rating, reviews_count, existing_id))

            self.conn.commit()
            self.checkpoint.data["stats"]["merged"] += 1
            return "merged"

        final_pid = place_id if place_id else f"synth_{lat:.6f}_{lng:.6f}"
        cursor.execute("""
            INSERT INTO places (
                place_id, cid, title, title_normalized, category, address,
                address_detailed, phone, website, rating, reviews_count,
                reviews_data, photos_data, opening_hours, lat, lng,
                osm_nearest_street, osm_neighborhood, osm_nearest_landmark,
                source_tier, corridor_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            final_pid,
            place.get("cid"),
            title,
            title_norm,
            place.get("category"),
            place.get("address"),
            place.get("address_detailed"),
            place.get("phone"),
            place.get("website"),
            place.get("rating"),
            place.get("reviews_count"),
            json.dumps(place.get("reviews_data"), ensure_ascii=False) if place.get("reviews_data") else None,
            json.dumps(place.get("photos_data"), ensure_ascii=False) if place.get("photos_data") else None,
            json.dumps(place.get("opening_hours"), ensure_ascii=False) if place.get("opening_hours") else None,
            lat,
            lng,
            place.get("osm_nearest_street"),
            place.get("osm_neighborhood"),
            place.get("osm_nearest_landmark"),
            place.get("source_tier", "tier1_gosom_grid"),
            place.get("corridor_key")
        ))
        self.conn.commit()
        self.checkpoint.data["stats"]["inserted"] += 1
        return "inserted"

    def export_geojson(self, output_file: str = "ibb_places.geojson"):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM places")
        features = []
        for row in cursor.fetchall():
            d = dict(row)
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [d["lng"], d["lat"]]
                },
                "properties": {k: v for k, v in d.items() if k not in ["lat", "lng"]}
            }
            features.append(feature)

        doc = {"type": "FeatureCollection", "features": features}
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"[DedupEngine] Exported {len(features)} points to {output_file}")

    def export_csv(self, output_file: str = "ibb_places.csv"):
        import csv
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM places ORDER BY title")
        rows = cursor.fetchall()
        if not rows:
            print("[DedupEngine] No rows to export.")
            return

        headers = [col[0] for col in cursor.description]
        with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in rows:
                writer.writerow(list(r))
        print(f"[DedupEngine] Exported {len(rows)} records to {output_file}")
