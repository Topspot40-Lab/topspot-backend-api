from __future__ import annotations

import argparse
import re
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import MusicDocuseries, MusicDocuseriesLocale
from backend.services.xai_client import ask_xai

def clean_story_text(value: str) -> str:
    value = value.strip()
    value = value.removeprefix("```text").removeprefix("```").removesuffix("```").strip()
    value = value.replace("**", "")
    value = re.sub(r"\(Word count:.*?\)\s*$", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"^The British Invasion\s*", "", value).strip()
    return value


def build_prompt(title: str, target_length: str) -> str:
    return f"""
Create a TopSpot Music Docuseries narration script.

TITLE:
{title}

TARGET LENGTH:
{target_length}

RULES:
- English only
- Warm, engaging, audio-first storytelling
- Do not sound like Wikipedia
- Write like a music documentary narrator
- Include vivid context, memorable examples, and cultural impact
- Avoid markdown headings
- Avoid bullet points
- Do not mention TopSpot
- Make it suitable for older listeners, music fans, libraries, and assisted living audiences
- End with a satisfying closing thought
- Do not include markdown
- Do not include a title
- Do not include word counts
- Do not include notes to the editor
- Return only the narration text

Approximate length:
- short: 700-900 words
- standard: 1200-1600 words
- feature: 1800-2400 words
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.language != "en":
        raise SystemExit("This starter script only generates English for now.")

    with Session(engine) as session:
        item = session.exec(
            select(MusicDocuseries).where(MusicDocuseries.slug == args.slug)
        ).first()

        if not item:
            raise SystemExit(f"Docuseries item not found: {args.slug}")

        locale = session.exec(
            select(MusicDocuseriesLocale)
            .where(MusicDocuseriesLocale.docuseries_id == item.id)
            .where(MusicDocuseriesLocale.language_code == args.language)
        ).first()

        if locale and locale.story_text and not args.overwrite:
            print("Existing story text found. Use --overwrite to replace.")
            return

        prompt = build_prompt(item.title, item.target_length or "standard")
        story_text = ask_xai(
            "You create warm, engaging, factual music documentary narration scripts for TopSpot.",
            prompt,
            temperature=0.5,
        )

        story_text = clean_story_text(story_text)

        print("=" * 80)
        print(item.title)
        print("=" * 80)
        print(story_text)
        print("=" * 80)
        print(f"Words: {len(story_text.split())}")
        print(f"Save mode: {args.save}")

        if not args.save:
            return

        if not locale:
            locale = MusicDocuseriesLocale(
                docuseries_id=item.id,
                language_code=args.language,
                story_text=story_text,
            )
            session.add(locale)
        else:
            locale.story_text = story_text

        session.commit()
        print("✅ Music Docuseries story text saved.")


if __name__ == "__main__":
    main()