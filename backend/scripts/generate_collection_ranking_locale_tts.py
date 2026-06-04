from __future__ import annotations

import argparse
import re
from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import (
    Collection,
    CollectionTrackRanking,
    CollectionTrackRankingLocale,
)
import tempfile
from pathlib import Path

from backend.config.tts_config import TTS_PROFILES
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import upload_bytes

HERITAGE_SLUGS = (
    "mexican_american_favorites",
    "traditional_mexican_favorites",
    "great_american_songbook",
    "crooner_classics",
    "traditional_hymns",
    "southern_gospel_favorites",
    "bluegrass_favorites",
    "patriotic_favorites",
    "railroad_train_songs",
    "cowboy_songs_western_favorites",
    "american_folk_heroes",
    "western_heritage_favorites",
    "civil_war_songs",
    "celtic_favorites",
    "italian_favorites",
    "german_heritage_favorites",
    "brazilian_classics",
    "african_american_heritage_favorites",
)


def bucket_for_lang(lang: str) -> str:
    if lang == "es":
        return "audio-es"
    if lang == "pt-BR":
        return "audio-ptbr"
    return "audio-en"


def tts_key_for(collection_slug: str, ranking: int) -> str:
    return f"collections-intros/{collection_slug}_{ranking:02d}.mp3"


def profile_for_lang(lang: str) -> dict:
    return TTS_PROFILES[lang]["intro"]


def normalize_years_for_tts(text: str, lang: str) -> str:
    def year_to_words_es(year: int) -> str:
        units = {
            0: "cero", 1: "uno", 2: "dos", 3: "tres", 4: "cuatro",
            5: "cinco", 6: "seis", 7: "siete", 8: "ocho", 9: "nueve",
            10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce",
            15: "quince", 16: "dieciséis", 17: "diecisiete", 18: "dieciocho",
            19: "diecinueve", 20: "veinte", 21: "veintiuno", 22: "veintidós",
            23: "veintitrés", 24: "veinticuatro", 25: "veinticinco",
            26: "veintiséis", 27: "veintisiete", 28: "veintiocho",
            29: "veintinueve",
        }
        tens = {
            30: "treinta", 40: "cuarenta", 50: "cincuenta",
            60: "sesenta", 70: "setenta", 80: "ochenta", 90: "noventa",
        }

        if 1900 <= year <= 1999:
            last_two = year - 1900
            if last_two == 0:
                return "mil novecientos"
            if last_two < 30:
                return f"mil novecientos {units[last_two]}"
            ones = last_two % 10

            if ones == 0:
                return f"mil novecientos {tens[last_two]}"

            return f"mil novecientos {tens[last_two // 10 * 10]} y {units[ones]}"

        if 2000 <= year <= 2029:
            last_two = year - 2000
            if last_two == 0:
                return "dos mil"
            if last_two < 30:
                return f"dos mil {units[last_two]}"

        return str(year)

    def year_to_words_ptbr(year: int) -> str:
        units = {
            0: "zero", 1: "um", 2: "dois", 3: "três", 4: "quatro",
            5: "cinco", 6: "seis", 7: "sete", 8: "oito", 9: "nove",
            10: "dez", 11: "onze", 12: "doze", 13: "treze", 14: "quatorze",
            15: "quinze", 16: "dezesseis", 17: "dezessete", 18: "dezoito",
            19: "dezenove", 20: "vinte", 21: "vinte e um", 22: "vinte e dois",
            23: "vinte e três", 24: "vinte e quatro", 25: "vinte e cinco",
            26: "vinte e seis", 27: "vinte e sete", 28: "vinte e oito",
            29: "vinte e nove",
        }
        tens = {
            30: "trinta", 40: "quarenta", 50: "cinquenta",
            60: "sessenta", 70: "setenta", 80: "oitenta", 90: "noventa",
        }

        if 1900 <= year <= 1999:
            last_two = year - 1900
            if last_two == 0:
                return "mil novecentos"
            if last_two < 30:
                return f"mil novecentos e {units[last_two]}"
            ones = last_two % 10

            if ones == 0:
                return f"mil novecentos e {tens[last_two]}"

            return f"mil novecentos e {tens[last_two // 10 * 10]} e {units[ones]}"

        if 2000 <= year <= 2029:
            last_two = year - 2000
            if last_two == 0:
                return "dois mil"
            if last_two < 30:
                return f"dois mil e {units[last_two]}"

        return str(year)

    def replace_year(match: re.Match[str]) -> str:
        year = int(match.group(0))

        if lang == "es":
            return year_to_words_es(year)

        if lang == "pt-BR":
            return year_to_words_ptbr(year)

        return str(year)

    return re.sub(r"\b(19\d{2}|20[0-2]\d)\b", replace_year, text)


def main(lang: str, limit: int | None, overwrite: bool) -> None:
    with Session(engine) as session:
        stmt = (
            select(CollectionTrackRankingLocale, CollectionTrackRanking, Collection)
            .join(
                CollectionTrackRanking,
                CollectionTrackRanking.id == CollectionTrackRankingLocale.collection_track_ranking_id,
            )
            .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
            .where(CollectionTrackRankingLocale.lang == lang)
            .order_by(Collection.slug, CollectionTrackRanking.ranking)
        )

        rows = session.exec(stmt).all()

        generated = 0
        skipped = 0
        attempted = 0

        for locale, ranking, collection in rows:
            if limit is not None and attempted >= limit:
                break

            attempted += 1

            if locale.tts_key and not overwrite:
                skipped += 1
                continue

            if not locale.intro_text:
                skipped += 1
                continue

            key = tts_key_for(collection.slug, ranking.ranking)
            bucket = bucket_for_lang(lang)

            try:
                profile = profile_for_lang(lang)
                voice_id = profile["voice_id"]
                settings = profile["settings"]

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp_path = Path(tmp.name)

                try:
                    tts_text = normalize_years_for_tts(locale.intro_text, lang)

                    generate_tts_mp3(
                        text=tts_text,
                        out_path=tmp_path,
                        voice_id=voice_id,
                        overwrite=True,
                        play=False,
                        settings=settings,
                        language=lang,
                    )

                    upload_bytes(
                        bucket,
                        key,
                        tmp_path.read_bytes(),
                        content_type="audio/mpeg",
                    )

                finally:
                    tmp_path.unlink(missing_ok=True)

                locale.tts_key = key
                generated += 1

                print(f"Generated {lang}: {collection.slug} #{ranking.ranking}")
                print(f"Attempted: {attempted}")

            except Exception as e:
                print(f"ERROR {collection.slug} #{ranking.ranking}: {e}")

        session.commit()

        print("\nDone.")
        print(f"Generated: {generated}")
        print(f"Skipped: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=["es", "pt-BR"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()

    main(lang=args.lang, limit=args.limit, overwrite=args.overwrite)