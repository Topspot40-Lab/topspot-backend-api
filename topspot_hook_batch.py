"""Batch improved hooks for scheduled, unreleased TopSpot40 documentaries.

Run from topspot-youtube-scheduler with topspot_hook_replacements.py beside it.
The inventory is a fixed allowlist. Rendering preserves the source audio.
No original is retired until its private replacement has passed verification.
"""
from __future__ import annotations
import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
import topspot_hook_replacements as engine


def clean_text(value):
    """Repair reversible UTF-8/cp1252 mojibake, preserving valid Unicode."""
    def word(match):
        text = match.group(0)
        for _ in range(4):
            try:
                candidate = text.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
            if candidate == text:
                break
            text = candidate
        return text
    return re.sub(r"\S+", word, value)


def clean_snippet(original, language):
    result = {key: copy.deepcopy(original[key]) for key in (
        "title", "description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage"
    ) if key in original}
    for key in ("title", "description"):
        result[key] = clean_text(result[key])
    result["tags"] = [clean_text(tag) for tag in result.get("tags", [])]
    result.update(defaultLanguage=language, defaultAudioLanguage=language)
    return result


def load_renderer(studio):
    sys.path.insert(0, str(studio))
    import backend
    import backend.studio
    import backend.studio.render
    backend.__path__.append(str(studio / "backend"))
    backend.studio.__path__.append(str(studio / "backend/studio"))
    backend.studio.render.__path__.append(str(studio / "backend/studio/render"))
    from backend.studio.render.hook_title_frame import render_hook_title_frame
    return render_hook_title_frame


def render(row, renderer):
    from PIL import Image
    slug, language = row["key"].split("|")
    source = Path(row["files"]["video"])
    hook = Path(row["files"]["hook"])
    opening = Path(row["files"]["opening"])
    # source is topic/factory/delivery/language/documentary.mp4
    root = source.parents[3]
    output_dir = root / "updated-hook-batch" / language
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "documentary.mp4"
    inputs_path = output_dir / "render-inputs.json"
    start = engine.duration(opening) if opening.is_file() else 6.5
    hook_duration = engine.duration(hook)
    engine.require(hook_duration > 2, f"Hook too short: {row['key']}")
    end = start + hook_duration + 1.25
    engine.require(end < engine.duration(source), "Hook timeline exceeds the source video.")
    # Check the hook boundary against the published story chapter when available.
    intro = hook.with_name("intro.mp3")
    chapters = list(re.finditer(r"(?m)^(\d+):(\d{2})(?::(\d{2}))?\s+([^\n]+)",
                               clean_text(row["snippet"]["description"])))
    if len(chapters) >= 2 and intro.is_file():
        chapter = chapters[1]
        label = chapter.group(4).lower()
        if any(word in label for word in ("story", "historia", "hist\u00f3ria")):
            timestamp = (int(chapter.group(1)) * 3600 + int(chapter.group(2)) * 60 + int(chapter.group(3))) if chapter.group(3) else (
                int(chapter.group(1)) * 60 + int(chapter.group(2)))
            expected_story = end + engine.duration(intro) + .75
            engine.require(abs(timestamp - expected_story) <= 3,
                           f"Hook timing disagrees with published story chapter for {row['key']}; review this video separately.")
    title = clean_text(row["snippet"]["title"]).split(" | ")[0]
    fingerprint = {"source_sha256": engine.digest(source), "hook_sha256": engine.digest(hook),
                   "title": title, "language": language, "start": start, "end": end,
                   "format_version": 1}
    source_image = output_dir / "hook_source.png"
    frame = output_dir / "hook_title.png"
    if output.exists():
        engine.require(inputs_path.is_file() and json.loads(inputs_path.read_text()) == fingerprint,
                       f"Existing output inputs differ: {output}. Move it aside before restarting.")
        engine.require(frame.is_file(), "Cached hook title frame is missing.")
        print("REUSING RENDER", row["key"], flush=True)
    else:
        print("RENDERING", row["key"], "opening", start, "seconds; audio copied unchanged", flush=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start + hook_duration / 2),
                        "-i", str(source), "-frames:v", "1", "-update", "1", str(source_image)], check=True)
        renderer(source_image, frame, title=title, language=language)
        temporary = output_dir / "documentary.rendering.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-stats", "-y",
            "-i", str(source), "-loop", "1", "-framerate", "30", "-i", str(frame),
            "-filter_complex", f"[0:v][1:v]overlay=enable='gte(t,{start})*lt(t,{end})':shortest=1[v]",
            "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-preset", "fast",
            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(temporary)
        ], check=True)
        engine.require(abs(engine.duration(temporary) - engine.duration(source)) < .25, "Video duration changed.")
        engine.require(engine.audio_hash(temporary) == engine.audio_hash(source), "Audio differs from source.")
        temporary.replace(output)
        engine.save(inputs_path, fingerprint)
    engine.require(abs(engine.duration(output) - engine.duration(source)) < .25, "Cached video duration differs.")
    engine.require(engine.audio_hash(output) == engine.audio_hash(source), "Cached video audio differs.")
    thumb = output_dir / "thumbnail.jpg"
    from backend.studio.youtube.thumbnail_badge import save_language_thumbnail
    save_language_thumbnail(frame, thumb, language)
    engine.require(thumb.stat().st_size < 2097152, "Thumbnail exceeds 2 MiB.")
    print("RENDER VERIFIED", row["key"], output, flush=True)
    return {"video": str(output), "sha256": engine.digest(output),
            "thumbnail": str(thumb), "thumbnail_sha256": engine.digest(thumb),
            "hook_start": start, "hook_end": end}


def caption_cache(api, original_id, directory):
    directory.mkdir(parents=True, exist_ok=True)
    index = directory / "caption-cache.json"
    if index.exists():
        cached = json.loads(index.read_text())
        engine.require(cached["old_id"] == original_id, "Caption cache identity changed.")
        for item in cached["captions"]:
            engine.require(engine.digest(item["path"]) == item["sha256"], "Cached captions changed.")
        return cached["captions"]
    captions = []
    for track in api.captions().list(part="snippet", videoId=original_id).execute().get("items", []):
        snippet = track["snippet"]
        if snippet.get("trackKind", "").lower() == "asr":
            continue
        engine.require(snippet.get("status") == "serving", "Original captions are not ready.")
        destination = directory / f"{track['id']}.vtt"
        body = api.captions().download(id=track["id"], tfmt="vtt").execute()
        destination.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
        captions.append({"path": str(destination), "sha256": engine.digest(destination),
                         "language": snippet["language"], "name": clean_text(snippet.get("name", "")) or snippet["language"]})
    engine.require(captions, "No authored captions found; original schedule retained.")
    engine.save(index, {"old_id": original_id, "captions": captions})
    return captions


def prepare_online(api, row, assets, path, playlists):
    key = row["key"]
    original = engine.video(api, row["video_id"])
    engine.check_old(original, key)
    engine.require(clean_text(original["snippet"]["title"]) == clean_text(row["snippet"]["title"]),
                   f"Original title changed since rendering: {key}")
    members = []
    for playlist in playlists:
        if api.playlistItems().list(part="id", playlistId=playlist["id"], videoId=row["video_id"], maxResults=1).execute().get("items"):
            members.append(playlist["id"])
    engine.require(members, f"No original playlists found: {key}")
    captions = caption_cache(api, row["video_id"], path.parent / "captions" / key.replace("|", "_"))
    # Keep an untouched snapshot as well as canonical upload/verification metadata.
    snapshot = copy.deepcopy(original)
    original["snippet"] = clean_snippet(original["snippet"], key.split("|")[1])
    return dict(assets, old_id=row["video_id"], original=original, original_unmodified=snapshot,
                publish_at=row["publish_at"], captions=captions, playlists=members, stage="prepared")


def synchronize_metadata(api, record, key):
    """Repair transport/display encoding and wait for correct live readback."""
    current = engine.video(api, record["new_id"])
    desired = record["original"]["snippet"]
    fields = ("title", "description", "tags", "defaultLanguage", "defaultAudioLanguage")
    if all(current["snippet"].get(field) == desired.get(field) for field in fields):
        return
    # Force an ASCII-only JSON request payload to eliminate ambiguous text encoding.
    request = api.videos().update(part="snippet", body={"id": record["new_id"], "snippet": desired})
    request.body = json.dumps({"id": record["new_id"], "snippet": desired}, ensure_ascii=True)
    request.execute()
    for attempt in range(20):
        current = engine.video(api, record["new_id"])
        if all(current["snippet"].get(field) == desired.get(field) for field in fields):
            return
        if attempt < 19:
            time.sleep(2)
    raise RuntimeError(f"Metadata readback is still updating for {key}; rerun the batch.")


def wait_ready(api, record, seconds):
    deadline = time.monotonic() + seconds
    while True:
        current = engine.video(api, record["new_id"])
        processing = current.get("processingDetails", {}).get("processingStatus")
        engine.require(processing not in ("failed", "terminated"), "YouTube processing failed.")
        tracks = api.captions().list(part="snippet", videoId=record["new_id"]).execute().get("items", [])
        captions_ready = all(any(item["snippet"].get("language") == caption["language"] and
                                 item["snippet"].get("name", "") == caption["name"] and
                                 item["snippet"].get("status") == "serving" for item in tracks)
                             for caption in record["captions"])
        if processing == "succeeded" and captions_ready:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Processing/captions still pending; private replacement saved. Rerun later.")
        print("Waiting for processing/captions", record["new_id"], flush=True)
        time.sleep(30)


def fix_updated(api, rows):
    for row in rows:
        if not row["already_updated"]:
            continue
        current = engine.video(api, row["video_id"])
        from datetime import datetime, timezone
        expected = engine.moment(row["publish_at"])
        scheduled = current["status"].get("publishAt")
        published = current["snippet"].get("publishedAt")
        schedule_matches = bool(
            scheduled and engine.moment(scheduled) == expected
        )
        released_on_time = bool(
            current["status"].get("privacyStatus") == "public"
            and expected <= datetime.now(timezone.utc)
            and published
            and 0 <= (engine.moment(published) - expected).total_seconds() <= 300
        )
        engine.require(schedule_matches or released_on_time,
                       "Updated video's schedule changed; review before editing metadata.")
        desired = clean_snippet(current["snippet"], row["key"].split("|")[1])
        synchronize_metadata(api, {"new_id": row["video_id"], "original": {"snippet": desired}}, row["key"])
        print("EXISTING METADATA VERIFIED", row["key"], flush=True)


def is_quota(error):
    content = getattr(error, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    text = (str(error) + str(content)).lower()
    return any(marker in text for marker in ("quotaexceeded", "dailylimitexceeded", "uploadlimitexceeded"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ("plan", "render-only", "run"):
        actions.add_argument("--" + name, action="store_true")
    parser.add_argument("--inventory", type=Path, default=Path("backend/studio/work/hook_batch_inventory_20260930.json"))
    parser.add_argument("--studio", type=Path, default=Path("E:/Documents/pp/topspot-backend-studio"))
    parser.add_argument("--limit", type=int, default=75)
    parser.add_argument("--max-uploads", type=int, default=15)
    parser.add_argument("--processing-wait", type=int, default=900)
    parser.add_argument("--fix-updated-metadata", action="store_true")
    args = parser.parse_args()
    engine.require(args.limit > 0 and args.max_uploads > 0, "Limits must be positive.")
    repo = Path.cwd()
    engine.require((repo / "backend/studio/work/youtube_release_state.json").is_file(), "Run from topspot-youtube-scheduler.")
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))["videos"]
    rows = sorted((row for row in inventory if not row["already_updated"]), key=lambda row: row["publish_at"])[:args.limit]
    engine.require(len({row['key'] for row in rows}) == len(rows), "Duplicate inventory keys.")
    engine.TARGETS = {row["key"]: row["video_id"] for row in rows}
    engine.EXPECTED = {row["key"]: row["publish_at"] for row in rows}
    folder = repo / "backend/studio/work/hook_batch_20260930"
    state_path = folder / "state.json"
    journal = json.loads(state_path.read_text()) if state_path.exists() else {
        "channel": engine.CHANNEL, "records": {}, "renders": {}, "failures": {}}
    engine.require(journal.get("channel") == engine.CHANNEL, "Wrong batch channel.")
    for row in rows:
        for name in ("video", "hook"):
            engine.require(Path(row["files"][name]).is_file(), f"Missing {name}: {row['key']}")
        record = journal["records"].get(row["key"])
        if not record or record.get("stage") != "active":
            engine.future(row["publish_at"])
    required_bytes = sum(Path(row["files"]["video"]).stat().st_size * 2 for row in rows
                         if row["key"] not in journal["renders"]) + 3 * 1024**3
    free = shutil.disk_usage(args.studio).free
    print(f"PLAN: {len(rows)} replacements; available disk {free/1024**3:.1f} GiB; estimated reserve {required_bytes/1024**3:.1f} GiB", flush=True)
    for row in rows:
        print(row["publish_at"], row["key"], flush=True)
    if args.plan:
        return
    engine.require(free > required_bytes, "Not enough free space for this render batch; reduce --limit or free disk space.")
    api = engine.connect(repo) if args.run else None
    if api and args.fix_updated_metadata:
        fix_updated(api, inventory)
    renderer = load_renderer(args.studio.resolve())
    for row in rows:
        key = row["key"]
        if key in journal["renders"]:
            engine.require(engine.digest(journal["renders"][key]["video"]) == journal["renders"][key]["sha256"], "Rendered file changed.")
            continue
        try:
            journal["renders"][key] = render(row, renderer)
            journal["failures"].pop(key, None)
        except Exception as error:
            journal["failures"][key] = str(error)
            print("RENDER SKIPPED", key, str(error), flush=True)
        engine.save(state_path, journal)
    if args.render_only:
        print("RENDER PHASE COMPLETE; YouTube unchanged. Review frames in updated-hook-batch folders.")
        return
    playlists = list(engine.pages(api.playlists().list, part="snippet", mine=True, maxResults=50))
    processed = 0
    for row in rows:
        key = row["key"]
        if key not in journal["renders"]:
            continue
        record = journal["records"].get(key)
        item_path = folder / "items" / (key.replace("|", "_") + ".json")
        if item_path.exists():
            checkpoint = json.loads(item_path.read_text())
            recovered = checkpoint["records"][key]
            engine.require(recovered["old_id"] == row["video_id"], "Item checkpoint identity changed.")
            record = journal["records"][key] = recovered
            engine.save(state_path, journal)
        if record and record["stage"] == "active":
            continue
        if processed >= args.max_uploads:
            print("UPLOAD BATCH LIMIT REACHED. Rerun the same command to continue.", flush=True)
            break
        try:
            if not record:
                record = prepare_online(api, row, journal["renders"][key], state_path, playlists)
                journal["records"][key] = record
                engine.save(state_path, journal)
            # Process one identity at a time through the tested upload/activation engine.
            engine.TARGETS = {key: row["video_id"]}
            singleton = {"channel": engine.CHANNEL, "records": {key: record}}
            try:
                if record["stage"] not in ("activating", "active"):
                    engine.upload(api, singleton, item_path)
                synchronize_metadata(api, record, key)
                wait_ready(api, record, args.processing_wait)
                engine.activate(api, singleton, item_path, repo)
            finally:
                engine.save(state_path, journal)
            processed += 1
            journal["failures"].pop(key, None)
            engine.save(state_path, journal)
        except Exception as error:
            journal["failures"][key] = str(error)
            engine.save(state_path, journal)
            if is_quota(error):
                print("QUOTA STOP. All progress saved. Rerun after YouTube's daily quota reset.", flush=True)
            else:
                print("BATCH STOP", key, str(error), flush=True)
            break
    active = sum(record["stage"] == "active" for record in journal["records"].values())
    print(f"BATCH STATUS: {len(journal['renders'])}/{len(rows)} rendered; {active}/{len(rows)} replacements active.", flush=True)
    print("Progress:", state_path, flush=True)
    print("End screens/cards still require a separate Studio check.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("STOP:", error, file=sys.stderr, flush=True)
        sys.exit(1)
