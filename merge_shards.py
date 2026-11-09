"""
Merges individual shard SQLite databases and checkpoint files into a master
SQLite, GeoJSON, CSV, and persistent checkpoint.json dataset.
"""

import os
import glob
import json
import sqlite3
from dedup_engine import DedupEngine


def merge_all_shards(
    shards_dir: str = "all_shards",
    master_db: str = "ibb_master_places.db",
    master_checkpoint: str = "checkpoint.json"
):
    master = DedupEngine(db_path=master_db, checkpoint_path=master_checkpoint)

    ckpt_files = glob.glob(os.path.join(shards_dir, "**", "checkpoint*.json"), recursive=True)
    completed_set = set(master.checkpoint.data.get("completed_cells", []))
    for cf in ckpt_files:
        try:
            with open(cf, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                for cid in cdata.get("completed_cells", []):
                    completed_set.add(cid)
        except Exception as e:
            print(f"  [Checkpoint Warning] Failed reading {cf}: {e}")

    master.checkpoint.data["completed_cells"] = sorted(list(completed_set))
    master.checkpoint.save()
    print(f"[Merge] Consolidated {len(completed_set)} completed grid cells into {master_checkpoint}")

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

    master.checkpoint.save()
    print(f"\n[Merge Complete] Unified dataset created with {total_merged} processed entities.")
    master.export_geojson("ibb_master_places.geojson")
    master.export_csv("ibb_master_places.csv")


if __name__ == "__main__":
    merge_all_shards()
