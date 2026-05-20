"""Download and cache the Chinook SQLite database on first run."""
from __future__ import annotations

from pathlib import Path

import requests

CHINOOK_URL = (
    "https://github.com/lerocha/chinook-database/raw/master/"
    "ChinookDatabase/DataSources/Chinook_Sqlite.sqlite"
)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "chinook.sqlite"


def ensure_database(db_path: Path = DB_PATH) -> Path:
    if db_path.exists() and db_path.stat().st_size > 0:
        return db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(CHINOOK_URL, timeout=60, stream=True)
    resp.raise_for_status()

    tmp = db_path.with_suffix(".part")
    with tmp.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    tmp.replace(db_path)
    return db_path


if __name__ == "__main__":
    path = ensure_database()
    print(f"Chinook ready at {path} ({path.stat().st_size / 1024:.1f} KB)")
