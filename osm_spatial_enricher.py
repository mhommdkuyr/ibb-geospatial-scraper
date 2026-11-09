"""
OpenStreetMap (OSM) Overpass API Spatial Join & Reverse Geocoding Engine.
"""

import math
import json
import os
import requests
from typing import List, Dict, Any, Tuple


def haversine_distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


class OSMSpatialEnricher:
    def __init__(self, cache_file: str = "osm_ibb_features.json"):
        self.cache_file = cache_file
        self.streets: List[Dict[str, Any]] = []
        self.buildings: List[Dict[str, Any]] = []
        self.neighborhoods: List[Dict[str, Any]] = []

    def fetch_osm_data_for_ibb(
        self,
        min_lat: float = 13.9300,
        min_lng: float = 44.1300,
        max_lat: float = 14.0300,
        max_lng: float = 44.2300,
        force_refresh: bool = False
    ) -> bool:
        if os.path.exists(self.cache_file) and not force_refresh:
            print(f"[OSM] Loading cached OSM data from {self.cache_file}...")
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._parse_osm_elements(data.get("elements", []))
            return True

        overpass_url = "https://overpass-api.de/api/interpreter"
        query = f"""
        [out:json][timeout:60];
        (
          way["highway"]({min_lat},{min_lng},{max_lat},{max_lng});
          way["building"]({min_lat},{min_lng},{max_lat},{max_lng});
          node["place"~"suburb|neighbourhood|quarter|town"]({min_lat},{min_lng},{max_lat},{max_lng});
          node["amenity"]({min_lat},{min_lng},{max_lat},{max_lng});
        );
        out body;
        >;
        out skel qt;
        """

        print("[OSM] Querying Overpass API for Ibb street and building geometries...")
        try:
            resp = requests.post(overpass_url, data={"data": query}, timeout=90)
            if resp.status_code == 200:
                data = resp.json()
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                self._parse_osm_elements(data.get("elements", []))
                print(f"[OSM] Successfully parsed and cached {len(self.streets)} streets, "
                      f"{len(self.buildings)} buildings, {len(self.neighborhoods)} neighborhoods.")
                return True
            else:
                print(f"[OSM Error] Overpass responded with HTTP {resp.status_code}")
                return False
        except Exception as e:
            print(f"[OSM Warning] Failed to query Overpass API: {e}. Falling back to default heuristics.")
            return False

    def _parse_osm_elements(self, elements: List[Dict[str, Any]]):
        nodes: Dict[int, Tuple[float, float]] = {}

        for el in elements:
            if el["type"] == "node" and "lat" in el and "lon" in el:
                nodes[el["id"]] = (el["lat"], el["lon"])
                tags = el.get("tags", {})
                if "place" in tags or "name" in tags or "name:ar" in tags:
                    name = tags.get("name:ar") or tags.get("name")
                    if name:
                        self.neighborhoods.append({
                            "name": name,
                            "type": tags.get("place") or tags.get("amenity") or "landmark",
                            "lat": el["lat"],
                            "lng": el["lon"],
                        })

        for el in elements:
            if el["type"] == "way":
                tags = el.get("tags", {})
                way_nodes = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
                if not way_nodes:
                    continue

                c_lat = sum(p[0] for p in way_nodes) / len(way_nodes)
                c_lng = sum(p[1] for p in way_nodes) / len(way_nodes)
                name = tags.get("name:ar") or tags.get("name")

                if "highway" in tags:
                    self.streets.append({
                        "name": name if name else f"شارع فرعي ({tags.get('highway')})",
                        "has_official_name": bool(name),
                        "type": tags.get("highway"),
                        "nodes": way_nodes,
                        "center_lat": c_lat,
                        "center_lng": c_lng,
                    })
                elif "building" in tags:
                    self.buildings.append({
                        "name": name if name else tags.get("building"),
                        "has_name": bool(name),
                        "nodes": way_nodes,
                        "center_lat": c_lat,
                        "center_lng": c_lng,
                    })

    def enrich_place_address(self, place: Dict[str, Any]) -> Dict[str, Any]:
        lat = place.get("lat")
        lng = place.get("lng")
        if not lat or not lng:
            return place

        nearest_street = None
        min_street_dist = float("inf")

        for street in self.streets:
            for s_lat, s_lng in street["nodes"]:
                d = haversine_distance_meters(lat, lng, s_lat, s_lng)
                if d < min_street_dist:
                    min_street_dist = d
                    nearest_street = street

        nearest_hood = None
        min_hood_dist = float("inf")
        for hood in self.neighborhoods:
            d = haversine_distance_meters(lat, lng, hood["lat"], hood["lng"])
            if d < min_hood_dist:
                min_hood_dist = d
                nearest_hood = hood

        nearest_bldg = None
        min_bldg_dist = float("inf")
        for bldg in self.buildings:
            if bldg["has_name"]:
                d = haversine_distance_meters(lat, lng, bldg["center_lat"], bldg["center_lng"])
                if d < min_bldg_dist:
                    min_bldg_dist = d
                    nearest_bldg = bldg

        street_name = nearest_street["name"] if nearest_street else "شارع غير مسمى"
        hood_name = nearest_hood["name"] if (nearest_hood and min_hood_dist < 1500) else "وسط المدينة"

        address_parts = ["اليمن", "محافظة إب", "مدينة إب", f"حي {hood_name}", street_name]

        if nearest_bldg and min_bldg_dist <= 50:
            address_parts.append(f"بالقرب من {nearest_bldg['name']}")

        synthesized_addr = " - ".join(address_parts)

        place["osm_nearest_street"] = street_name
        place["osm_street_distance_m"] = round(min_street_dist, 1) if min_street_dist != float("inf") else None
        place["osm_neighborhood"] = hood_name
        place["osm_nearest_landmark"] = nearest_bldg["name"] if (nearest_bldg and min_bldg_dist <= 75) else None
        place["osm_synthesized_address_ar"] = synthesized_addr

        google_addr = place.get("address", "")
        if not google_addr or google_addr in ["Ibb", "إب", "Yemen", "اليمن"]:
            place["address_detailed"] = synthesized_addr
        else:
            place["address_detailed"] = f"{google_addr} ({synthesized_addr})"

        return place
