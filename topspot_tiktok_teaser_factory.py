"""Build a reviewable vertical TikTok teaser from a TopSpot40 documentary.

Example, from any directory on Gary's Windows computer:
  python topspot_tiktok_teaser_factory.py \
    --work-root E:/Documents/pp/topspot-backend-studio/backend/studio/work \
    --slug george_martin --language en \
    --output-root E:/Documents/pp/topspot-tiktok-teasers \
    --title "George Martin: The Fifth Beatle"

Requires ffmpeg, ffprobe, and Pillow. This script never posts to TikTok.
The uploaded tts_config.py detail voices and settings are the defaults.
Use --prepare-endings --output-root PATH --env-file .env to save all three
reusable ending MP3s before rendering teasers. Future runs reuse these files.
The end card lasts at least seven seconds and holds one second after speech.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from PIL import Image, ImageDraw, ImageFont


HOOK_PAUSE_SECONDS = 1.25
CARD_SECONDS = 7.0
ENDING_TAIL_SECONDS = 1.0
WIDTH, HEIGHT = 1080, 1920

COPY = {
    "en": ("FULL STORY ON YOUTUBE", "EXPLORE MORE MUSIC & STORIES", "FOLLOW @topspot40"),
    "es": ("HISTORIA COMPLETA EN YOUTUBE", "MÁS MÚSICA E HISTORIAS", "SIGUE A @topspot40"),
    "pt-BR": ("HISTÓRIA COMPLETA NO YOUTUBE", "MAIS MÚSICA E HISTÓRIAS", "SIGA @topspot40"),
}
SERIES_LABEL = {
    "en": "MUSIC DOCUMENTARY",
    "es": "DOCUMENTAL MUSICAL",
    "pt-BR": "DOCUMENTÁRIO MUSICAL",
}
ENDING_COPY = {
    "en": "Every song has a story. Find more on the TopSpot40 YouTube channel and at TopSpot40 dot com.",
    "es": "Cada canción tiene una historia. Descubre más en el canal de YouTube de TopSpot40 y en TopSpot40 punto com.",
    "pt-BR": "Toda música tem uma história. Descubra mais no canal do TopSpot40 no YouTube e em TopSpot40 ponto com.",
}
DETAIL_PROFILES = {
    "en": {"voice_id": "pqHfZKP75CvOlQylNhV4", "settings": {"stability": 0.6, "similarity_boost": 0.6, "style": 0.2, "use_speaker_boost": False}},
    "es": {"voice_id": "94zOad0g7T7K4oa7zhDq", "settings": {"stability": 0.65, "similarity_boost": 0.7, "style": 0.25, "use_speaker_boost": False}},
    "pt-BR": {"voice_id": "cyD08lEy76q03ER1jZ7y", "settings": {"stability": 0.65, "similarity_boost": 0.7, "style": 0.25, "use_speaker_boost": False}},
}


def local_environment(args: argparse.Namespace) -> dict[str, str]:
    values = {}
    if args.env_file:
        if not args.env_file.is_file():
            raise SystemExit(f"Missing environment file: {args.env_file}")
        for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.strip().removeprefix("export ").partition("=")
            if separator and name.strip() in {"ELEVENLABS_API_KEY", "ELEVENLABS_MODEL", "ELEVENLABS_MODEL_ES", "ELEVENLABS_MODEL_PT_BR"}:
                values[name.strip()] = value.strip().strip("\"'")
    values.update({key: value for key, value in os.environ.items() if key.startswith("ELEVENLABS_")})
    return values


def ending_audio(args: argparse.Namespace) -> Path | None:
    if args.ending_audio:
        if not args.ending_audio.is_file():
            raise SystemExit(f"Missing ending narration: {args.ending_audio}")
        return args.ending_audio
    environment = local_environment(args)
    profile = DETAIL_PROFILES[args.language]
    model_variable = {"en": "ELEVENLABS_MODEL", "es": "ELEVENLABS_MODEL_ES", "pt-BR": "ELEVENLABS_MODEL_PT_BR"}[args.language]
    settings = {"text": ENDING_COPY[args.language],
                "voice_id": args.ending_voice_id or profile["voice_id"],
                "voice_settings": profile["settings"],
                "model_id": args.ending_model_id or environment.get(model_variable, "eleven_turbo_v2_5")}
    if settings["model_id"] in {"eleven_turbo_v2_5", "eleven_flash_v2_5"}:
        settings["language_code"] = {"en": "en", "es": "es", "pt-BR": "pt"}[args.language]
    directory = args.output_root / "_shared" / "endings"
    output = directory / f"ending_{args.language}.mp3"
    metadata = output.with_suffix(".json")
    if output.exists() or metadata.exists():
        if output.is_file() and metadata.is_file():
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if saved.get("settings") == settings and saved.get("sha256") == hashlib.sha256(output.read_bytes()).hexdigest() and duration(output) > 0:
                print(f"Reusing saved ending: {output}", flush=True)
                return output
        raise SystemExit(f"Saved ending changed or does not match its settings: {output}. Move the MP3 and JSON aside if you intend to generate a replacement.")
    api_key = environment.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise SystemExit("Set ELEVENLABS_API_KEY locally or pass --env-file with your existing .env path.")
    request = Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{settings['voice_id']}?output_format=mp3_44100_128",
        data=json.dumps({key: value for key, value in settings.items() if key != "voice_id"}).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    print(f"Generating reusable {args.language} ending narration…", flush=True)
    try:
        with urlopen(request, timeout=120) as response:
            audio_bytes = response.read()
    except HTTPError as error:
        raise SystemExit(f"ElevenLabs returned HTTP {error.code}; check your voice, model, and account locally.") from None
    except URLError:
        raise SystemExit("Could not reach ElevenLabs; check your connection.") from None
    directory.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".temporary.mp3")
    temporary.write_bytes(audio_bytes)
    try:
        if duration(temporary) <= 0:
            raise ValueError("Ending narration has no duration")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    metadata.write_text(json.dumps({"settings": settings, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved ending: {output}", flush=True)
    return output


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [Path("C:/Windows/Fonts/segoeuib.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")]
        if bold else
        [Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/arial.ttf")]
    )
    candidates += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
                        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    raise RuntimeError("No suitable font found; pass this on a Windows machine with Segoe UI installed.")


def centered(draw: ImageDraw.ImageDraw, label: str, y: int, size: int,
             color: str, bold: bool = False) -> None:
    face = font(size, bold)
    while draw.textlength(label, font=face) > WIDTH - 300 and size > 26:
        size -= 2
        face = font(size, bold)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=face)
    draw.text(((WIDTH - (right - left)) / 2, y - top), label, fill=color, font=face)


def display_youtube_url(url: str) -> str:
    if not url:
        return "youtube.com/@topspot40"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if not video_id and parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/")[2]
        if video_id:
            return f"youtu.be/{video_id}"
    if host in {"youtu.be", "www.youtu.be"} and parsed.path.strip("/"):
        return f"youtu.be/{parsed.path.strip('/')}"
    raise ValueError("--youtube-url must be a YouTube video URL")


def paste_logo(image: Image.Image, logo: Path | None, box: tuple[int, int, int, int]) -> None:
    if not logo:
        return
    with Image.open(logo) as original:
        mark = original.convert("RGBA")
        mark.thumbnail((box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS)
        x = (box[0] + box[2] - mark.width) // 2
        y = (box[1] + box[3] - mark.height) // 2
        image.paste(mark, (x, y), mark)


def make_card(path: Path, language: str, youtube_url: str, logo: Path | None,
              title: str) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0b101a")
    draw = ImageDraw.Draw(image)
    gold, white, muted, red = "#f5bd31", "#f7f7f7", "#b6bbc6", "#dd322f"
    draw.rounded_rectangle((80, 235, 1000, 1670), radius=44,
                           outline="#8a691e", width=3, fill="#111823")
    if logo:
        paste_logo(image, logo, (305, 310, 775, 510))
    else:
        centered(draw, "TopSpot", 325, 101, gold, True)
        centered(draw, "40", 432, 97, red, True)
    subject, separator, subtitle = title.partition(":")
    draw.line((285, 570, 795, 570), fill=gold, width=4)
    centered(draw, subject.strip().upper(), 640, 72, gold, True)
    if separator:
        centered(draw, subtitle.strip(), 750, 59, white, True)
    heading, _, follow = COPY[language]
    centered(draw, heading, 970, 49, muted, True)
    centered(draw, display_youtube_url(youtube_url), 1052, 58, white, True)
    centered(draw, "TopSpot40.com", 1290, 77, gold, True)
    centered(draw, follow, 1485, 47, white, True)
    image.save(path)


def make_brand_overlay(path: Path) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((215, 1390, 865, 1525), radius=27,
                           fill=(8, 10, 16, 225), outline="#a77e25", width=3)
    centered(draw, "TopSpot40.com", 1425, 63, "#f5bd31", True)
    image.save(path)


def make_title_overlay(path: Path, language: str, title: str) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for y in range(120, 580):
        alpha = int(196 * (580 - y) / 460)
        draw.line((0, y, WIDTH, y), fill=(8, 10, 16, alpha), width=1)
    subject, separator, subtitle = title.partition(":")
    centered(draw, subject.strip().upper(), 205, 76, "#f5bd31", True)
    if separator:
        words = subtitle.strip().split()
        lines: list[str] = []
        current = ""
        face = font(60, True)
        for word in words:
            candidate = (current + " " + word).strip()
            if current and draw.textlength(candidate, font=face) > 835:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for index, line in enumerate(lines[:2]):
            centered(draw, line, 305 + index * 73, 60, "#f7f7f7", True)
    draw.line((400, 450, 680, 450), fill="#f5bd31", width=4)
    centered(draw, SERIES_LABEL[language], 485, 37, "#e0e2e8", True)
    image.save(path)


def build(args: argparse.Namespace) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe must be on PATH")
    factory = args.work_root / args.slug / "factory"
    opening = factory / "shared" / "opening.mp4"
    delivery = factory / "delivery" / args.language
    hook = delivery / "narration" / "hook.mp3"
    documentary = delivery / "documentary.mp4"
    sources = (hook, documentary)
    if args.start_seconds is None:
        sources = (opening,) + sources
    for source in sources:
        if not source.is_file():
            raise SystemExit(f"Missing source: {source}")

    start = (
        duration(opening) if args.start_seconds is None
        else args.start_seconds
    )
    if not 0 <= start < float("inf"):
        raise SystemExit("--start-seconds must be finite and nonnegative")
    hook_seconds = duration(hook)
    cut = start + hook_seconds + HOOK_PAUSE_SECONDS
    teaser_seconds = cut - start
    total = duration(documentary)
    if not 5 < cut < total - 1:
        raise SystemExit(f"Unsafe cut: {cut:.3f}s of a {total:.3f}s documentary")
    narration = ending_audio(args)
    narration_seconds = duration(narration) if narration else 0.0
    card_seconds = max(CARD_SECONDS, narration_seconds + ENDING_TAIL_SECONDS)

    output_dir = args.output_root / args.slug
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{args.slug}_{args.language}_tiktok_preview.mp4"
    manifest = output_dir / f"{args.slug}_{args.language}_review.json"
    card_path = output_dir / f"{args.slug}_{args.language}_end_card.png"
    title_path = output_dir / f"{args.slug}_{args.language}_title_overlay.png"
    brand_path = output_dir / f"{args.slug}_{args.language}_brand_overlay.png"
    if args.logo and not args.logo.is_file():
        raise SystemExit(f"Missing logo: {args.logo}")
    visible_title = args.title or args.slug.replace("_", " ").title()
    make_card(card_path, args.language, args.youtube_url, args.logo, visible_title)
    make_title_overlay(title_path, args.language, visible_title)
    make_brand_overlay(brand_path)

    # Enlarge the 16:9 source modestly to give the story art more of the screen.
    # A blurred copy fills the rest of the vertical canvas.
    filters = (
        f"[0:v]trim=start={start:.6f}:end={cut:.6f},setpts=PTS-STARTPTS,split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:1[blur];"
        "[fg]scale=1500:-2,crop=1080:844:(in_w-out_w)*0.55:(in_h-out_h)/2[main];"
        "[blur][main]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[base];"
        f"[1:v]trim=duration={teaser_seconds:.6f},setpts=PTS-STARTPTS,"
        "format=rgba[title];"
        "[base][title]overlay=0:0:shortest=1[titled];"
        f"[4:v]trim=duration={teaser_seconds:.6f},setpts=PTS-STARTPTS,format=rgba[brand];"
        "[titled][brand]overlay=0:0:shortest=1,format=yuv420p[hook_video];"
        f"[0:a]atrim=start={start:.6f}:end={cut:.6f},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"afade=t=out:st={max(0, teaser_seconds - .35):.6f}:d=0.35[hook_audio];"
        f"[2:v]trim=duration={card_seconds:.6f},setpts=PTS-STARTPTS,"
        "fps=30,format=yuv420p[end_card];"
        "[3:a]asetpts=PTS-STARTPTS,aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad,atrim=duration={card_seconds:.6f}[end_audio];"
        "[hook_video][hook_audio][end_card][end_audio]"
        "concat=n=2:v=1:a=1[v][a]"
    )
    narration_input = (["-i", str(narration)] if narration else
                       ["-f", "lavfi", "-t", str(card_seconds), "-i",
                        "anullsrc=channel_layout=stereo:sample_rate=48000"])
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(documentary),
        "-loop", "1", "-framerate", "30", "-i", str(title_path),
        "-loop", "1", "-framerate", "30", "-i", str(card_path),
        *narration_input,
        "-loop", "1", "-framerate", "30", "-i", str(brand_path),
        "-filter_complex", filters, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-t", f"{teaser_seconds + card_seconds:.6f}", str(output),
    ]
    print(f"Two parts: {teaser_seconds:.3f}s hook with title overlay "
          f"+ {card_seconds:.3f}s ending", flush=True)
    subprocess.run(command, check=True)
    review = {
        "slug": args.slug, "language": args.language, "title": args.title,
        "youtube_url": args.youtube_url, "website": "https://topspot40.com",
        "logo_image": str(args.logo) if args.logo else None,
        "ending_audio": str(narration) if narration else None,
        "ending_text": ENDING_COPY[args.language],
        "ending_audio_seconds": round(narration_seconds, 3),
        "ending_card_seconds": round(card_seconds, 3),
        "source_documentary": str(documentary), "start_seconds": round(start, 3),
        "cut_seconds": round(cut, 3), "hook_audio_seconds": round(hook_seconds, 3),
        "preview_file": str(output), "status": "review_only_not_uploaded",
    }
    manifest.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Review video: {output}")
    print(f"Review details: {manifest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path,
                        help="The backend/studio/work directory containing story slugs")
    parser.add_argument("--slug")
    parser.add_argument("--language", choices=tuple(COPY), default="en")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--youtube-url", default="")
    parser.add_argument("--logo", type=Path, help="Optional transparent TopSpot40 logo PNG; otherwise use a text wordmark")
    ending = parser.add_mutually_exclusive_group()
    ending.add_argument("--ending-audio", type=Path, help="Existing ending MP3 to play over the final card")
    ending.add_argument("--ending-voice-id", help="Existing ElevenLabs narrator voice ID; generates and reuses a shared ending MP3")
    parser.add_argument("--ending-model-id", help="Override the model from tts_config defaults or local environment")
    parser.add_argument("--env-file", type=Path, help="Existing local .env file containing ELEVENLABS_API_KEY")
    parser.add_argument("--prepare-endings", action="store_true", help="Generate or reuse EN, ES, and PT-BR endings without rendering a video")
    parser.add_argument(
        "--start-seconds", type=float, default=None,
        help="Verified hook start time; overrides opening.mp4 duration"
    )
    args = parser.parse_args()
    if args.prepare_endings:
        if args.ending_audio:
            parser.error("--prepare-endings generates shared endings; use --ending-audio when rendering a video")
        if not shutil.which("ffprobe"):
            parser.error("ffprobe must be on PATH")
        for language in COPY:
            args.language = language
            ending_audio(args)
    else:
        if not args.work_root or not args.slug:
            parser.error("--work-root and --slug are required to render a teaser")
        build(args)
