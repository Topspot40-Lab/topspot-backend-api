from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

import requests
from sqlalchemy import func, or_
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Track, Artist
from backend.models.collection_models import CollectionTrackRanking


XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip()
XAI_MODEL = os.getenv("XAI_MODEL", "grok-2-latest").strip()


def clean_text(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\*\*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(' "\n\t')


def call_xai_batch(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not XAI_API_KEY:
        raise RuntimeError("XAI_API_KEY missing")

    system = """
You generate concise, engaging track detail blurbs for a music app.

Return ONLY a JSON array. No markdown. No commentary.
Each item must include:
- track_id
- track_name
- artist_name
- detail_text

Rules for detail_text:
- Exactly 4 complete sentences
- The intro has already said the song title and artist name
- Do not start by repeating the artist name and song title
- Do not mechanically repeat the artist name, song title, rank, year, or collection name
- Sentence 1 should begin with the song's meaning, message, emotion, background, recording story, or impact
- Sentences 2 and 3 should explain the meaning, emotion, message, background, or listener appeal
- Sentence 4 should include one concrete fact about the song, artist, history, recording, chart impact, or legacy when possible
- Do not invent fictional scenes
- Avoid generic descriptions that could apply to many songs
- No DJ patter
"""

    user = "Create detail_text for these tracks:\n\n" + json.dumps(
        items,
        ensure_ascii=False,
    )

    response = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {XAI_API_KEY}"},
        json={
            "model": XAI_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 1600,
        },
        timeout=120,
    )

    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()

    content = content.strip().strip("`")
    if content.lower().startswith("json"):
        content = content[4:].strip()

    data = json.loads(content)
    if not isinstance(data, list):
        raise RuntimeError("xAI response was not a JSON list")

    return data


def main(lang: str, limit: int | None, track_id: int | None, overwrite: bool, collection_ids: str | None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection-ids", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    collection_ids = [
        int(x.strip())
        for x in args.collection_ids.split(",")
        if x.strip()
    ]

    print("=" * 80)
    print("Generate Missing Track Detail Text")
    print(f"Collections: {collection_ids}")
    print(f"Limit:       {args.limit}")
    print(f"Save:        {args.save}")
    print("=" * 80)

    with Session(engine) as session:
        rows = session.exec(
            select(
                Track.id,
                Track.track_name,
                Track.artist_display_name,
                Artist.artist_name,
                Track.year_released,
            )
            .join(Artist, Artist.id == Track.artist_id)
            .join_from(Track, __import__("backend.models.collection_models", fromlist=["CollectionTrackRanking"]).CollectionTrackRanking)
            .where(__import__("backend.models.collection_models", fromlist=["CollectionTrackRanking"]).CollectionTrackRanking.collection_id.in_(collection_ids))
            .where(
                or_(
                    Track.detail.is_(None),
                    func.trim(Track.detail) == "",
                    func.lower(Track.detail) == "null",
                )
            )
            .order_by(Track.id)
            .limit(args.limit)
        ).all()

        items = []
        for row in rows:
            artist_name = row.artist_display_name or row.artist_name
            items.append(
                {
                    "track_id": row.id,
                    "track_name": row.track_name,
                    "artist_name": artist_name,
                    "year_released": row.year_released,
                }
            )

        print(f"Found missing details: {len(items)}")

        if not items:
            return

        for item in items:
            print(f"- {item['track_id']} | {item['artist_name']} - {item['track_name']}")

        results = call_xai_batch(items)

        updated = 0
        for result in results:
            track_id = result.get("track_id")
            detail_text = clean_text(result.get("detail_text") or "")

            if not track_id or not detail_text:
                continue

            print("-" * 80)
            print(f"{track_id}")
            print(detail_text)

            if args.save:
                track = session.get(Track, int(track_id))
                if track:
                    track.detail = detail_text
                    session.add(track)
                    updated += 1

        if args.save:
            session.commit()

        print("=" * 80)
        print(f"Updated: {updated}")
        print("=" * 80)


if __name__ == "__main__":
    main()
