"""Idempotent schema migration for reviewed localized publishing content."""
from __future__ import annotations
import argparse
from sqlalchemy import text
from backend.database import engine
COLUMNS=("localized_publishing_content_json TEXT","localized_publishing_content_sha256 VARCHAR(64)","localized_publishing_content_source_sha256 VARCHAR(64)","localized_publishing_content_reviewed_at TIMESTAMPTZ","localized_publishing_content_reviewed_by TEXT")
def main() -> None:
 p=argparse.ArgumentParser(); p.add_argument("--apply",action="store_true"); a=p.parse_args()
 if not a.apply: print("Dry run: add reviewed localized publishing content columns to artist_story and music_docuseries_locale"); return
 with engine.begin() as connection:
  for table in ("artist_story","music_docuseries_locale"):
   for column in COLUMNS: connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}"))
 print("Migration complete; no content was backfilled or approved.")
if __name__ == "__main__": main()