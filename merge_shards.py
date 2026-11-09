"""
Merges individual shard SQLite databases into a master SQLite, GeoJSON, and CSV dataset.
"""

import os
import glob
import sqlite3
from dedup_engine import DedupEngine


def merge_all_shards(shards_dir: str = "all_shards", master_db: str = "ibb_master_places.db"):
    master = DedupEngine(db_path=master_db)
    shard_dbs = glob.glob(os.path.join(shards_dir, "**", "*.db"), recursive=True)
    print(f"[Merge] Found {len(shard_dbs)} shard database files to merge into {master_db}...")

    total_merged = 0
    for s_db in shard_dbs:
        if os.path.abspath(s_db) == os.path.abspath(master_db):
            continue
        print(f"  [Merge] Reading {s_db}...")
        try:
            conn = sqlite3.connect(s_db)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM places")
            rows = cur.fetchall()
            for r in rows:
                status = master.upsert_place(dict(r))
                if status in ["inserted", "merged"]:
                    total_merged += 1
            conn.close()
        except Exception as e:
            print(f"  [Merge Error] Failed to read {s_db}: {e}")

    print(f"\n[Merge Complete] Unified dataset created with {total_merged} processed entities.")
    master.export_geojson("ibb_master_places.geojson")
    master.export_csv("ibb_master_places.csv")


if __name__ == "__main__":
    merge_all_shards()
