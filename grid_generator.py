"""
Adaptive Micro-Grid Generator for Ibb Governorate and High-Density City Corridors.
"""

import math
import json
import argparse
from typing import List, Dict, Any, Tuple
from config import IBB_GOVERNORATE_BBOX, IBB_CITY_BBOX, DENSE_CORRIDORS


def meters_to_lat_deg(meters: float) -> float:
    return meters / 111132.954


def meters_to_lng_deg(meters: float, lat_deg: float) -> float:
    rad = math.radians(lat_deg)
    return meters / (111412.84 * math.cos(rad) - 93.5 * math.cos(3 * rad))


def is_inside_bbox(lat: float, lng: float, bbox: Dict[str, float]) -> bool:
    return (bbox["min_lat"] <= lat <= bbox["max_lat"] and
            bbox["min_lng"] <= lng <= bbox["max_lng"])


def find_matching_dense_corridor(lat: float, lng: float) -> Tuple[str, Dict]:
    for key, corridor in DENSE_CORRIDORS.items():
        if is_inside_bbox(lat, lng, corridor):
            return key, corridor
    return "", {}


class AdaptiveGridGenerator:
    def __init__(self):
        self.cells: List[Dict[str, Any]] = []

    def generate_corridor_grids(self) -> List[Dict[str, Any]]:
        corridor_cells = []
        cell_id = 0

        for key, corridor in DENSE_CORRIDORS.items():
            step_m = corridor.get("grid_step_m", 40)
            zoom = corridor.get("zoom", 21)
            name_ar = corridor.get("name_ar", key)

            lat_step = meters_to_lat_deg(step_m)
            avg_lat = (corridor["min_lat"] + corridor["max_lat"]) / 2.0
            lng_step = meters_to_lng_deg(step_m, avg_lat)

            lat = corridor["min_lat"]
            while lat <= corridor["max_lat"]:
                lng = corridor["min_lng"]
                while lng <= corridor["max_lng"]:
                    cell_id += 1
                    cell = {
                        "cell_id": f"dense_{key}_{cell_id:05d}",
                        "corridor_key": key,
                        "zone_name": name_ar,
                        "center_lat": round(lat + lat_step / 2.0, 6),
                        "center_lng": round(lng + lng_step / 2.0, 6),
                        "min_lat": round(lat, 6),
                        "max_lat": round(lat + lat_step, 6),
                        "min_lng": round(lng, 6),
                        "max_lng": round(lng + lng_step, 6),
                        "step_meters": step_m,
                        "zoom": zoom,
                        "tier": "tier3_panning_dense",
                        "priority": 1,
                    }
                    corridor_cells.append(cell)
                    lng += lng_step
                lat += lat_step

        return corridor_cells

    def generate_city_general_grid(self, dense_cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        city_cells = []
        bbox = IBB_CITY_BBOX
        step_m = bbox["grid_step_m"]
        zoom = bbox["zoom"]

        lat_step = meters_to_lat_deg(step_m)
        avg_lat = (bbox["min_lat"] + bbox["max_lat"]) / 2.0
        lng_step = meters_to_lng_deg(step_m, avg_lat)

        cell_id = 0
        lat = bbox["min_lat"]
        while lat <= bbox["max_lat"]:
            lng = bbox["min_lng"]
            while lng <= bbox["max_lng"]:
                cell_id += 1
                c_lat = lat + lat_step / 2.0
                c_lng = lng + lng_step / 2.0

                corridor_key, _ = find_matching_dense_corridor(c_lat, c_lng)
                if not corridor_key:
                    cell = {
                        "cell_id": f"city_{cell_id:05d}",
                        "corridor_key": "general_city",
                        "zone_name": "مدينة إب - النطاق الحضري العام",
                        "center_lat": round(c_lat, 6),
                        "center_lng": round(c_lng, 6),
                        "min_lat": round(lat, 6),
                        "max_lat": round(lat + lat_step, 6),
                        "min_lng": round(lng, 6),
                        "max_lng": round(lng + lng_step, 6),
                        "step_meters": step_m,
                        "zoom": zoom,
                        "tier": "tier1_gosom_grid",
                        "priority": 2,
                    }
                    city_cells.append(cell)
                lng += lng_step
            lat += lat_step

        return city_cells

    def generate_rural_governorate_grid(self) -> List[Dict[str, Any]]:
        rural_cells = []
        bbox = IBB_GOVERNORATE_BBOX
        step_m = bbox["grid_step_m"]
        zoom = bbox["zoom"]

        lat_step = meters_to_lat_deg(step_m)
        avg_lat = (bbox["min_lat"] + bbox["max_lat"]) / 2.0
        lng_step = meters_to_lng_deg(step_m, avg_lat)

        cell_id = 0
        lat = bbox["min_lat"]
        while lat <= bbox["max_lat"]:
            lng = bbox["min_lng"]
            while lng <= bbox["max_lng"]:
                cell_id += 1
                c_lat = lat + lat_step / 2.0
                c_lng = lng + lng_step / 2.0

                if not is_inside_bbox(c_lat, c_lng, IBB_CITY_BBOX):
                    cell = {
                        "cell_id": f"rural_{cell_id:06d}",
                        "corridor_key": "rural_governorate",
                        "zone_name": "محافظة إب - المديريات والأرياف",
                        "center_lat": round(c_lat, 6),
                        "center_lng": round(c_lng, 6),
                        "min_lat": round(lat, 6),
                        "max_lat": round(lat + lat_step, 6),
                        "min_lng": round(lng, 6),
                        "max_lng": round(lng + lng_step, 6),
                        "step_meters": step_m,
                        "zoom": zoom,
                        "tier": "tier1_gosom_grid",
                        "priority": 3,
                    }
                    rural_cells.append(cell)
                lng += lng_step
            lat += lat_step

        return rural_cells

    def generate_full_adaptive_grid(self, include_rural: bool = True) -> List[Dict[str, Any]]:
        print("[Grid] Generating ultra-dense commercial corridors (40m micro-grid)...")
        dense = self.generate_corridor_grids()
        print(f"[Grid] Generated {len(dense)} ultra-dense micro-cells.")

        print("[Grid] Generating general urban Ibb city grid (120m)...")
        city = self.generate_city_general_grid(dense)
        print(f"[Grid] Generated {len(city)} city-level cells.")

        all_cells = dense + city

        if include_rural:
            print("[Grid] Generating rural governorate grid (500m)...")
            rural = self.generate_rural_governorate_grid()
            print(f"[Grid] Generated {len(rural)} rural cells.")
            all_cells.extend(rural)

        self.cells = all_cells
        return all_cells

    def export_geojson(self, output_path: str):
        features = []
        for cell in self.cells:
            poly = [
                [
                    [cell["min_lng"], cell["min_lat"]],
                    [cell["max_lng"], cell["min_lat"]],
                    [cell["max_lng"], cell["max_lat"]],
                    [cell["min_lng"], cell["max_lat"]],
                    [cell["min_lng"], cell["min_lat"]],
                ]
            ]
            feature = {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": poly},
                "properties": {
                    "cell_id": cell["cell_id"],
                    "zone_name": cell["zone_name"],
                    "zoom": cell["zoom"],
                    "tier": cell["tier"],
                    "step_m": cell["step_meters"],
                    "center_lat": cell["center_lat"],
                    "center_lng": cell["center_lng"],
                },
            }
            features.append(feature)

        geojson_doc = {"type": "FeatureCollection", "features": features}
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(geojson_doc, f, ensure_ascii=False, indent=2)
        print(f"[Grid] GeoJSON exported to {output_path} ({len(features)} polygons).")

    def export_shards(self, total_shards: int, output_dir: str):
        import os
        os.makedirs(output_dir, exist_ok=True)
        shards: List[List[Dict[str, Any]]] = [[] for _ in range(total_shards)]
        for idx, cell in enumerate(self.cells):
            shard_idx = idx % total_shards
            shards[shard_idx].append(cell)

        for s_idx, shard_data in enumerate(shards):
            shard_file = os.path.join(output_dir, f"grid_shard_{s_idx:02d}.json")
            with open(shard_file, "w", encoding="utf-8") as f:
                json.dump(shard_data, f, ensure_ascii=False, indent=2)
        print(f"[Grid] Sharded {len(self.cells)} cells into {total_shards} shards in {output_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Adaptive Micro-Grid Generator for Ibb")
    parser.add_argument("--scope", choices=["city", "full"], default="city")
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--out-geojson", type=str, default="ibb_grid.geojson")
    parser.add_argument("--shards-dir", type=str, default="shards")
    args = parser.parse_args()

    gen = AdaptiveGridGenerator()
    cells = gen.generate_full_adaptive_grid(include_rural=(args.scope == "full"))
    gen.export_geojson(args.out_geojson)
    gen.export_shards(args.shards, args.shards_dir)
