from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")

DIVIDERS = [
    {
        "filename": "part1_story.html",
        "part": "PART I",
        "title": "The TopSpot40 Story",
        "text": "How a software project became a journey through music, memory, storytelling, and discovery.",
    },
    {
        "filename": "part2_artists.html",
        "part": "PART II",
        "title": "Featured Artists",
        "text": "The voices, performers, and stories that shaped generations.",
    },
    {
        "filename": "part3_nostalgia.html",
        "part": "PART III",
        "title": "Nostalgia Programs",
        "text": "Sixty-four ranked programs spanning eight decades and eight genres.",
    },
    {
        "filename": "part4_collections.html",
        "part": "PART IV",
        "title": "Collections",
        "text": "Music organized by stories, themes, heritage, memories, and shared experiences.",
    },
    {
        "filename": "part5_getting_started.html",
        "part": "PART V",
        "title": "Getting Started",
        "text": "How to listen, explore, and use TopSpot40 as a guided music discovery experience.",
    },
]


def build_page(part: str, title: str, text: str) -> str:
    return f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            color: #111;
            background: white;
        }}

        .page {{
            width: 8.5in;
            min-height: 11in;
            box-sizing: border-box;
            padding: 0.75in;
            display: flex;
            flex-direction: column;
            justify-content: center;
            text-align: center;
        }}

        .part {{
            font-size: 28px;
            letter-spacing: 4px;
            color: #777;
            margin-bottom: 28px;
        }}

        h1 {{
            font-size: 54px;
            margin: 0 0 28px;
            text-transform: uppercase;
        }}

        .text {{
            font-size: 24px;
            line-height: 1.45;
            max-width: 680px;
            margin: 0 auto;
            color: #333;
        }}

        .footer {{
            position: absolute;
            bottom: 0.45in;
            left: 0.75in;
            right: 0.75in;
            font-size: 13px;
            color: #777;
            border-top: 1px solid #ddd;
            padding-top: 10px;
        }}
    </style>
</head>
<body>
<section class="page">
    <div class="part">{part}</div>
    <h1>{title}</h1>
    <div class="text">{text}</div>

    <div class="footer">
        TopSpot40.com — Discovery Never Ends
    </div>
</section>
</body>
</html>
"""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for divider in DIVIDERS:
        path = OUTPUT_DIR / divider["filename"]
        path.write_text(
            build_page(
                part=divider["part"],
                title=divider["title"],
                text=divider["text"],
            ),
            encoding="utf-8",
        )
        print(f"Generated: {path}")


if __name__ == "__main__":
    main()