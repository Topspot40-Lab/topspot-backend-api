from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine
from backend.services.supabase_storage import upload_bytes
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.config.tts_config import TTS_PROFILES


LOCALE_ID = 1054
LANG = "es"
BUCKET = "audio-es"
KEY = "decade-genre-intro/1950s_latin_global_13.mp3"


def main() -> None:
    voice_id = TTS_PROFILES[LANG]["artist"]["voice_id"]

    with Session(engine) as session:
        row = session.exec(
            text("""
                select id, intro_text
                from public.track_ranking_locale
                where id = :id
            """).bindparams(id=LOCALE_ID)
        ).first()

        if not row:
            raise SystemExit(f"track_ranking_locale row not found: {LOCALE_ID}")

        intro_text = row[1]

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp_path = Path(tmp.name)

        try:
            generate_tts_mp3(
                text=intro_text,
                out_path=tmp_path,
                voice_id=voice_id,
                overwrite=True,
                language=LANG,
            )

            audio_bytes = tmp_path.read_bytes()

            upload_bytes(
                bucket=BUCKET,
                key=KEY,
                data=audio_bytes,
                content_type="audio/mpeg",
            )

            session.exec(
                text("""
                    update public.track_ranking_locale
                    set tts_bucket = :bucket,
                        tts_key = :key
                    where id = :id
                """).bindparams(
                    bucket=BUCKET,
                    key=KEY,
                    id=LOCALE_ID,
                )
            )

            session.commit()
            print(f"✅ Uploaded {BUCKET}/{KEY}")
            print(f"✅ Updated track_ranking_locale.id = {LOCALE_ID}")

        finally:
            if tmp_path.exists():
                tmp_path.unlink()


if __name__ == "__main__":
    main()