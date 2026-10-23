"""Download/refresh local maps: python -m backend.scripts.sync_osm_extracts."""
import json

from backend.app.osm_snapshots import SnapshotStore
from backend.app.settings import SOURCE_CACHE


def main():
    previous = None

    def progress(**values):
        nonlocal previous
        value = values["source_progress"]
        downloaded = (value.get("downloaded_bytes") or 0) // (50 * 1024**2)
        marker = (value["phase"], value["region"], downloaded)
        if marker != previous:
            print(json.dumps(value), flush=True)
            previous = marker

    store = SnapshotStore(SOURCE_CACHE / "osm-extracts-v1", progress=progress)
    try:
        result = store.sync(force=True)
        print(json.dumps({"snapshot_id": result["id"], "data_timestamp": result["data_timestamp"]}), flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    main()
