"""Render future-release TopSpot40 teasers locally, without API calls or uploads.

Run from topspot-youtube-scheduler. Titles are localized editorial drafts.
Reserve state is separate from publishing approvals and the saved calendar.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from topspot_tiktok_batch import digest, fingerprint, read, write

LANGS = ("en", "es", "pt-BR")
TITLES = {
    "afrobeats_meets_latin_america": ("Afrobeats Meets Latin America", "Afrobeats se encuentra con Latinoamérica", "Afrobeats encontra a América Latina"),
    "ai_future_of_music": ("AI and the Future of Music", "La IA y el futuro de la música", "A IA e o futuro da música"),
    "banda_sinaloense": ("The Story of Banda Sinaloense", "La historia de la banda sinaloense", "A história da banda sinaloense"),
    "birth_of_country_music": ("The Birth of Country Music", "El nacimiento de la música country", "O nascimento da música country"),
    "birth_of_jazz": ("The Birth of Jazz", "El nacimiento del jazz", "O nascimento do jazz"),
    "border_blasters": ("Border Blasters: Radio Across Borders", "Border Blasters: La radio que cruzó fronteras", "Border Blasters: O rádio que cruzou fronteiras"),
    "delta_to_chicago_blues": ("From the Delta to Chicago: The Blues", "Del Delta a Chicago: La historia del blues", "Do Delta a Chicago: A história do blues"),
    "disco_rise_backlash_revival": ("Disco: Rise, Backlash and Revival", "Disco: Auge, rechazo y renacimiento", "Disco: Ascensão, rejeição e renascimento"),
    "downloads_to_streaming": ("From Downloads to Streaming", "De las descargas al streaming", "Dos downloads ao streaming"),
    "eight_tracks_to_walkman": ("From 8-Tracks to the Walkman", "De los cartuchos de 8 pistas al Walkman", "Dos cartuchos de 8 pistas ao Walkman"),
    "golden_age_bolero": ("The Golden Age of Bolero", "La época de oro del bolero", "A era de ouro do bolero"),
    "gospel_shapes_popular_music": ("How Gospel Shaped Popular Music", "Cómo el góspel transformó la música popular", "Como o gospel transformou a música popular"),
    "heavy_metal_global_language": ("Heavy Metal: A Global Language", "Heavy metal: Un lenguaje global", "Heavy metal: Uma linguagem global"),
    "hip_hop_goes_global": ("Hip-Hop Goes Global", "El hip-hop conquista el mundo", "O hip-hop conquista o mundo"),
    "history_drum_machine": ("The History of the Drum Machine", "La historia de la caja de ritmos", "A história da bateria eletrônica"),
    "history_electric_guitar": ("The History of the Electric Guitar", "La historia de la guitarra eléctrica", "A história da guitarra elétrica"),
    "history_hammond_organ": ("The History of the Hammond Organ", "La historia del órgano Hammond", "A história do órgão Hammond"),
    "history_of_accordion": ("The History of the Accordion", "La historia del acordeón", "A história do acordeão"),
    "history_of_corrido": ("The History of the Corrido", "La historia del corrido", "A história do corrido"),
    "history_of_piano": ("The History of the Piano", "La historia del piano", "A história do piano"),
    "history_of_saxophone": ("The History of the Saxophone", "La historia del saxofón", "A história do saxofone"),
    "history_of_synthesizer": ("The History of the Synthesizer", "La historia del sintetizador", "A história do sintetizador"),
    "history_steel_guitar": ("The History of the Steel Guitar", "La historia de la steel guitar", "A história da steel guitar"),
    "house_techno_modern_dance_music": ("House, Techno and Modern Dance Music", "House, techno y la música electrónica de baile", "House, techno e a música eletrônica de dança"),
    "kpop_goes_global": ("K-Pop Goes Global", "El K-pop conquista el mundo", "O K-pop conquista o mundo"),
    "muscle_shoals_sound": ("The Muscle Shoals Sound", "El sonido de Muscle Shoals", "O som de Muscle Shoals"),
    "new_wave_synth_pop_around_the_world": ("New Wave and Synth-Pop Around the World", "New wave y synth-pop alrededor del mundo", "New wave e synth-pop pelo mundo"),
    "punk_rock_around_the_world": ("Punk Rock Around the World", "El punk rock alrededor del mundo", "O punk rock pelo mundo"),
    "punk_rock_revolution": ("The Punk Rock Revolution", "La revolución del punk rock", "A revolução do punk rock"),
    "reggae_goes_global": ("Reggae Goes Global", "El reggae conquista el mundo", "O reggae conquista o mundo"),
    "rise_of_45_and_jukebox": ("The Rise of the 45 and the Jukebox", "El auge del disco de 45 rpm y la rocola", "A ascensão do disco de 45 rpm e da jukebox"),
    "rise_of_bedroom_pop": ("The Rise of Bedroom Pop", "El auge del bedroom pop", "A ascensão do bedroom pop"),
    "rise_of_edm": ("The Rise of EDM", "El auge de la EDM", "A ascensão da EDM"),
    "sonidero_culture": ("The Story of Sonidero Culture", "La historia de la cultura sonidera", "A história da cultura sonidera"),
    "stax_memphis_soul": ("Stax and the Soul of Memphis", "Stax y el soul de Memphis", "Stax e o soul de Memphis"),
    "story_of_live_aid": ("The Story of Live Aid", "La historia de Live Aid", "A história do Live Aid"),
    "story_of_sun_records": ("The Story of Sun Records", "La historia de Sun Records", "A história da Sun Records"),
    "the_wrecking_crew": ("The Wrecking Crew: Behind the Hits", "The Wrecking Crew: Detrás de los éxitos", "The Wrecking Crew: Por trás dos sucessos"),
    "tiktok_fifteen_second_hit": ("TikTok and the Fifteen-Second Hit", "TikTok y el éxito de quince segundos", "TikTok e o sucesso de quinze segundos"),
    "vinyl_revival": ("The Vinyl Revival", "El regreso del vinilo", "O renascimento do vinil"),
}


def timing(path):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ], check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def make_spec(repo, work, root, slug, lang, title):
    factory = work / slug / "factory"
    inputs = [factory / "shared/opening.mp4",
              factory / "delivery" / lang / "documentary.mp4",
              factory / "delivery" / lang / "narration/hook.mp3",
              root / "_shared/endings" / f"ending_{lang}.mp3",
              repo / "topspot_tiktok_teaser_factory.py"]
    for source in inputs:
        if not source.is_file():
            raise RuntimeError(f"Missing source: {source}")
    return {
        "slug": slug, "language": lang, "title": title,
        "youtube_url": "",
        "ending_audio": str(inputs[3]), "start_seconds": timing(inputs[0]),
        "inputs": [fingerprint(p) for p in inputs],
        "factory_sha256": digest(inputs[4]),
    }


def reusable(record, spec, video, review):
    return bool(record and record.get("spec") == spec and video.is_file() and review.is_file()
                and record.get("video_sha256") == digest(video)
                and record.get("review_sha256") == digest(review))


def run(args):
    repo = Path(__file__).resolve().parent
    root = args.output_root
    work = args.work_root
    state_path = root / "_shared/reserve_state.json"
    state = read(state_path, {"schema_version": 1, "renders": {}})
    queue = read(root / "publishing_queue.json")
    if not queue:
        raise RuntimeError("Existing publishing queue is required")
    excluded = {j["slug"] for j in queue["jobs"]} | {"george_martin"}
    release = read(repo / "backend/studio/work/youtube_release_state.json", {"uploads": {}})
    uploads = release.get("uploads", {})

    def order(slug):
        dates = [uploads.get(f"{slug}|{lang}", {}).get("scheduled_publish_at") for lang in LANGS]
        dates = [datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
                 for v in dates if v]
        return (min(dates) if dates else "9999", slug)

    stories = sorted((s for s in TITLES if s not in excluded), key=order)
    if args.slug:
        if args.slug not in TITLES:
            raise RuntimeError("No localized title set for that story")
        stories = [s for s in stories if s == args.slug]
    completed = 0
    held = []
    for slug in stories:
        specs = {}
        try:
            for index, lang in enumerate(LANGS):
                specs[lang] = make_spec(repo, work, root, slug, lang, TITLES[slug][index])
        except RuntimeError as error:
            print("HOLD:", error, flush=True)
            held.append(slug)
            continue
        print(f"\nRESERVE {completed + 1}: {slug}", flush=True)
        for lang in LANGS:
            spec = specs[lang]
            folder = root / slug
            video = folder / f"{slug}_{lang}_tiktok_preview.mp4"
            review = folder / f"{slug}_{lang}_review.json"
            key = f"{slug}|{lang}"
            if reusable(state["renders"].get(key), spec, video, review):
                print("REUSE", key, flush=True)
            else:
                subprocess.run([
                    sys.executable, str(repo / "topspot_tiktok_teaser_factory.py"),
                    "--work-root", str(work), "--slug", slug, "--language", lang,
                    "--output-root", str(root), "--title", spec["title"],
                    "--youtube-url", spec["youtube_url"],
                    "--ending-audio", spec["ending_audio"],
                ], check=True)
            state["renders"][key] = {
                "spec": spec, "video_file": str(video), "review_file": str(review),
                "video_sha256": digest(video), "review_sha256": digest(review),
                "status": "reserve_awaiting_review_and_public_release",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            write(state_path, state)
        completed += 1
        print("REVIEW ALL THREE:", root / slug, flush=True)
        if completed >= args.limit:
            break
    state["last_batch"] = {"completed_stories": completed, "held_stories": held,
                           "finished_at": datetime.now(timezone.utc).isoformat()}
    write(state_path, state)
    print(f"\nRESERVE COMPLETE: {completed} stories / {completed * 3} previews; {len(held)} held.")
    print("No API calls, uploads, approvals, or publishing-calendar changes performed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--slug")
    parser.add_argument("--output-root", type=Path, default=Path("E:/Documents/pp/topspot-tiktok-teasers"))
    parser.add_argument("--work-root", type=Path, default=Path("E:/Documents/pp/topspot-backend-studio/backend/studio/work"))
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    lock = args.output_root / "_reserve_render.lock"
    descriptor = None
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        run(args)
    except Exception as error:
        print("STOPPED:", error, file=sys.stderr)
        sys.exit(1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
            lock.unlink()
