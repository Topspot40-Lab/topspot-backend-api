"""Check 2020s Pop DB snapshot, name collisions and reused narration audio.

    python -m backend.scripts.check_2020s_pop_preflight --plan 2020s-pop-reviewed.json --output 2020s-pop-preflight.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text


LANGUAGES = ("en", "es", "pt-BR")
BUCKETS = {"en": "audio-en", "es": "audio-es", "pt-BR": "audio-ptbr"}


def inspect(plan, connection, *, storage=True):
    from backend.services.supabase_storage import object_exists
    problems=[]
    warnings=[]
    existing=connection.execute(text("""
        SELECT tr.id AS ranking_id,tr.ranking,tr.track_id,t.spotify_track_id,tr.intro AS en_intro
        FROM track_ranking tr JOIN track t ON t.id=tr.track_id
        WHERE tr.decade_genre_id=:id ORDER BY tr.ranking
    """),{"id":plan["program"]["id"]}).mappings().all()
    snapshot=plan["snapshot_rankings"]
    if [(r["ranking_id"],r["ranking"],r["track_id"],r["spotify_track_id"],r["en_intro"]) for r in existing] != [
        (r["ranking_id"],r["ranking"],r["track_id"],r["spotify_track_id"],r["en_intro"]) for r in snapshot
    ]:
        problems.append("The 2020s Pop ranking snapshot changed")
    for saved in snapshot:
        locales=[dict(r) for r in connection.execute(text("""
            SELECT language_code,intro_text,tts_bucket,tts_key FROM track_ranking_locale
            WHERE track_ranking_id=:id ORDER BY language_code
        """),{"id":saved["ranking_id"]}).mappings().all()]
        if locales!=saved["locales"]:
            problems.append(f"Existing locales changed for ranking {saved['ranking_id']}")
    ranks={r["ranking"] for r in existing}
    if ranks|{a["rank"] for a in plan["additions"]}!=set(range(1,46)) or len(ranks)!=35:
        problems.append("Adding ten selected songs would not produce ranks 1–45")
    reused_audio=set()
    for a in plan["additions"]:
        if a["reuse_track_id"]:
            t=connection.execute(text("""
                SELECT id,artist_id,spotify_track_id,detail FROM track WHERE id=:id
            """),{"id":a["reuse_track_id"]}).mappings().one_or_none()
            if not t or t["spotify_track_id"]!=a["spotify_track_id"] or not t["detail"]:
                problems.append(f"Reused track changed at rank {a['rank']}")
            if a["reuse_artist_id"] and t and t["artist_id"]!=a["reuse_artist_id"]:
                problems.append(f"Reused track artist changed at rank {a['rank']}")
            for lang in LANGUAGES:
                reused_audio.add((BUCKETS[lang],f"detail/{a['spotify_track_id']}.mp3"))
            track_locales=connection.execute(text("""
                SELECT language_code,detail_text,tts_bucket,tts_key FROM track_locale
                WHERE track_id=:id
            """),{"id":a["reuse_track_id"]}).mappings().all()
            for lang in ("es","pt-BR"):
                locale=next((r for r in track_locales if r["language_code"]==lang),None)
                if not locale or not locale["detail_text"] or locale["tts_bucket"]!=BUCKETS[lang] or locale["tts_key"]!=f"detail/{a['spotify_track_id']}.mp3":
                    problems.append(f"Reused track detail missing or misplaced at rank {a['rank']}/{lang}")
        else:
            matches=connection.execute(text("SELECT id FROM track WHERE spotify_track_id=:sid"),{"sid":a["spotify_track_id"]}).scalars().all()
            if matches:
                problems.append(f"New track already exists at rank {a['rank']}")
            same_name=connection.execute(text("SELECT id,spotify_track_id FROM track WHERE lower(track_name)=lower(:name)"),{"name":a["title"]}).mappings().all()
            if same_name:
                warnings.append({"rank":a["rank"],"same_title_tracks":[dict(r) for r in same_name]})
        if a["reuse_artist_id"]:
            ar=connection.execute(text("""
                SELECT id,spotify_artist_id,artist_description FROM artist WHERE id=:id
            """),{"id":a["reuse_artist_id"]}).mappings().one_or_none()
            if not ar or ar["spotify_artist_id"]!=a["spotify_artist_id"] or not ar["artist_description"]:
                problems.append(f"Reused artist changed at rank {a['rank']}")
            for lang in LANGUAGES:
                reused_audio.add((BUCKETS[lang],f"artist/{a['spotify_artist_id']}.mp3"))
            artist_locales=connection.execute(text("""
                SELECT language_code,artist_description_text,tts_bucket,tts_key FROM artist_locale
                WHERE artist_id=:id
            """),{"id":a["reuse_artist_id"]}).mappings().all()
            for lang in ("es","pt-BR"):
                locale=next((r for r in artist_locales if r["language_code"]==lang),None)
                if not locale or not locale["artist_description_text"] or locale["tts_bucket"]!=BUCKETS[lang] or locale["tts_key"]!=f"artist/{a['spotify_artist_id']}.mp3":
                    problems.append(f"Reused artist bio missing or misplaced at rank {a['rank']}/{lang}")
        else:
            matches=connection.execute(text("SELECT id FROM artist WHERE spotify_artist_id=:sid"),{"sid":a["spotify_artist_id"]}).scalars().all()
            if matches:
                problems.append(f"New artist already exists at rank {a['rank']}")
            same_name=connection.execute(text("SELECT id,spotify_artist_id FROM artist WHERE lower(artist_name)=lower(:name)"),{"name":a["artist_name"]}).mappings().all()
            if same_name:
                warnings.append({"rank":a["rank"],"same_name_artists":[dict(r) for r in same_name]})
    missing=[]
    if storage:
        for bucket,key in sorted(reused_audio):
            if not object_exists(bucket,key):
                missing.append({"bucket":bucket,"key":key})
    return {"ready":not problems and not warnings and not missing,"problems":problems,
            "possible_name_collisions":warnings,"missing_reused_audio":missing,
            "existing_ranks":len(existing),"new_ranks":len(plan["additions"]),
            "reused_audio_checked":len(reused_audio)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    plan=json.loads(args.plan.read_text(encoding="utf-8"))
    from backend.database import engine
    with engine.connect() as connection:
        report=inspect(plan,connection)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"Ready: {report['ready']}; {report['existing_ranks']} existing + {report['new_ranks']} new; {report['reused_audio_checked']} reused audio files checked")
    print(f"Problems: {len(report['problems'])}; possible name collisions: {len(report['possible_name_collisions'])}; missing reused audio: {len(report['missing_reused_audio'])}")
    print(f"Saved {args.output}")
    if not report["ready"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
