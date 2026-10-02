"""Prepare, upload privately, and activate five approved hook replacements.

Run from topspot-youtube-scheduler. Originals and their audio are preserved.
This batch deliberately excludes the already replaced Vicente English video.
End screens/cards require a separate YouTube Studio check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

CHANNEL = "UCmxRTAuep6ZWHGZQYLnfYjA"
TARGETS = {
    "vicente_fernandez_vs_antonio_aguilar|es": "7FzlaoSuu2k",
    "vicente_fernandez_vs_antonio_aguilar|pt-BR": "eDUmArMsNO0",
    "les_paul|en": "1vudumGtVWc",
    "les_paul|es": "Pg-Ob3hTFGY",
    "les_paul|pt-BR": "7rXkBbGHIM8",
}
EXPECTED = {
    key: f"2026-{'09-30' if key.startswith('vicente') else '10-01'}T"
         f"{'20' if key.endswith('|es') else '16' if key.endswith('|en') else '00'}:00:00Z"
    for key in TARGETS
}
EXPECTED["vicente_fernandez_vs_antonio_aguilar|pt-BR"] = "2026-10-01T00:00:00Z"
EXPECTED["les_paul|pt-BR"] = "2026-10-02T00:00:00Z"
STATUS_KEYS = ("license", "embeddable", "publicStatsViewable",
               "selfDeclaredMadeForKids", "containsSyntheticMedia")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def moment(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def future(value):
    require(moment(value) > datetime.now(timezone.utc) + timedelta(minutes=15),
            f"Release time is too close or has passed: {value}. Stop and review schedules.")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def probe(path):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
    ], text=True))


def duration(path):
    return float(probe(path)["format"]["duration"])


def audio_hash(path):
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c:a", "copy",
        "-f", "streamhash", "-hash", "sha256", "-"
    ], text=True).strip()


def connect(repo):
    sys.path.insert(0, str(repo))
    from backend.studio.youtube.auth import SCOPES, TOKEN_PATH
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    require(TOKEN_PATH.is_file(), "Saved YouTube authorization not found.")
    credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    require(credentials.valid, "YouTube authorization needs renewal.")
    api = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    channels = api.channels().list(part="snippet", mine=True).execute()["items"]
    require(any(item["id"] == CHANNEL for item in channels), "Wrong YouTube account/channel.")
    return api


def video(api, identity):
    rows = api.videos().list(part="snippet,status,processingDetails", id=identity).execute().get("items", [])
    require(len(rows) == 1, f"Video unavailable: {identity}")
    require(rows[0]["snippet"]["channelId"] == CHANNEL, f"Wrong channel for video {identity}")
    return rows[0]


def check_old(item, key, retiring=False):
    status = item["status"]
    require(status["privacyStatus"] == "private", f"Original is no longer private: {key}")
    publish = status.get("publishAt")
    require((retiring and not publish) or (publish and moment(publish) == moment(EXPECTED[key])),
            f"Original schedule changed: {key}: {publish}")
    future(EXPECTED[key])


def pages(request, **kwargs):
    token = None
    while True:
        result = request(pageToken=token, **kwargs).execute()
        yield from result.get("items", [])
        token = result.get("nextPageToken")
        if not token:
            return


def prepare(api, studio, journal, journal_path):
    sys.path.insert(0, str(studio))
    # Scheduler imports backend first; extend package paths to find Studio's renderer.
    import backend
    import backend.studio
    import backend.studio.render
    backend.__path__.append(str(studio / "backend"))
    backend.studio.__path__.append(str(studio / "backend/studio"))
    backend.studio.render.__path__.append(str(studio / "backend/studio/render"))
    from backend.studio.render.hook_title_frame import render_hook_title_frame
    from PIL import Image

    playlists = list(pages(api.playlists().list, part="snippet", mine=True, maxResults=50))
    for key, old_id in TARGETS.items():
        if key in journal["records"]:
            print("Already prepared:", key, flush=True)
            continue
        original = video(api, old_id)
        check_old(original, key)
        slug, language = key.split("|")
        root = studio / "backend/studio/work" / slug
        source = root / "factory/delivery" / language / "documentary.mp4"
        require(source.is_file(), f"Original file missing: {source}")
        preview = root / "previews"
        preview.mkdir(exist_ok=True)
        frame = preview / f"hook_title_{language}.png"
        output = root / "updated-delivery" / language / "documentary.mp4"
        source_hash = digest(source)
        if slug == "les_paul":
            hook = root / "factory/delivery" / language / "narration/hook.mp3"
            opening = root / "factory/shared/opening.mp4"
            start = duration(opening)
            end = start + duration(hook) + 1.25
            image = preview / f"hook_source_{language}.png"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start + 2),
                            "-i", str(source), "-frames:v", "1", "-update", "1", str(image)], check=True)
            title = original["snippet"]["title"].split(" | ")[0]
            render_hook_title_frame(image, frame, title=title, language=language)
            fingerprint = {"source": source_hash, "frame": digest(frame), "start": start, "end": end}
            sidecar = output.with_suffix(".hook-inputs.json")
            if output.exists():
                require(sidecar.is_file() and json.loads(sidecar.read_text()) == fingerprint,
                        f"Existing output has unverified inputs; move it aside first: {output}")
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary = output.with_name("documentary.rendering.mp4")
                print("Rendering", key, "(audio copied unchanged)...", flush=True)
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "warning", "-stats", "-y",
                    "-i", str(source), "-loop", "1", "-framerate", "30", "-i", str(frame),
                    "-filter_complex", f"[0:v][1:v]overlay=enable='gte(t,{start})*lt(t,{end})':shortest=1[v]",
                    "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-preset", "fast",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(temporary)
                ], check=True)
                require(abs(duration(temporary) - duration(source)) < .25, "Rendered duration changed.")
                require(audio_hash(temporary) == audio_hash(source), "Rendered audio differs from original.")
                os.replace(temporary, output)
                save(sidecar, fingerprint)
        require(frame.is_file() and output.is_file(), f"Approved frame or output missing: {key}")
        require(abs(duration(output) - duration(source)) < .25, f"Video duration changed: {key}")
        require(audio_hash(output) == audio_hash(source), f"Audio changed: {key}")
        thumb = preview / f"hook_thumbnail_{language}.jpg"
        with Image.open(frame) as picture:
            picture.convert("RGB").save(thumb, quality=90)
        require(thumb.stat().st_size < 2097152, "Thumbnail exceeds 2 MiB.")
        memberships = []
        for playlist in playlists:
            if api.playlistItems().list(part="id", playlistId=playlist["id"], videoId=old_id, maxResults=1).execute().get("items"):
                memberships.append(playlist["id"])
        require(memberships, f"No live playlists found for {key}.")
        tracks = api.captions().list(part="snippet", videoId=old_id).execute().get("items", [])
        captions = []
        for track in tracks:
            snippet = track["snippet"]
            if snippet.get("trackKind") == "ASR" or snippet.get("trackKind", "").lower() == "asr":
                continue
            require(snippet.get("status") == "serving", f"Original caption not serving: {key}")
            target = preview / f"replacement_caption_{track['id']}.vtt"
            body = api.captions().download(id=track["id"], tfmt="vtt").execute()
            target.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
            captions.append({"path": str(target), "sha256": digest(target),
                             "language": snippet["language"], "name": snippet.get("name", ""),
                             "isCC": snippet.get("isCC", False)})
        # Existing release records explicitly report uploaded captions: fail if lost.
        require(captions, f"No authored captions found for {key}; review before uploading.")
        record = {"old_id": old_id, "original": original, "publish_at": original["status"]["publishAt"],
                  "video": str(output), "sha256": digest(output), "thumbnail": str(thumb),
                  "thumbnail_sha256": digest(thumb), "captions": captions, "playlists": memberships,
                  "stage": "prepared"}
        journal["records"][key] = record
        save(journal_path, journal)
        print("PREPARED", key, record["publish_at"], output, flush=True)
    print("PREPARATION COMPLETE. No YouTube videos were changed.", flush=True)


def upload(api, journal, path):
    from googleapiclient.http import MediaFileUpload
    from backend.studio.youtube.uploader import set_thumbnail, add_to_playlist
    require(set(journal["records"]) == set(TARGETS), "Run --prepare first.")
    for key, record in journal["records"].items():
        if record.get("stage") == "active":
            continue
        check_old(video(api, record["old_id"]), key)
        require(digest(record["video"]) == record["sha256"], f"Prepared video changed: {key}")
        require(digest(record["thumbnail"]) == record["thumbnail_sha256"], "Thumbnail changed.")
        for caption in record["captions"]:
            require(digest(caption["path"]) == caption["sha256"], "Caption file changed.")
        if not record.get("new_id"):
            require(record["stage"] != "uploading", f"Upload outcome unknown for {key}; inspect Studio before retrying.")
            snippet = record["original"]["snippet"]
            language = key.split("|")[1]
            body = {"snippet": {name: snippet[name] for name in ("title", "description", "tags", "categoryId") if name in snippet},
                    "status": writable_status(record["original"])}
            body["snippet"].update(defaultLanguage=language, defaultAudioLanguage=language)
            # Private, unscheduled until --activate; mark synthetic media explicitly.
            body["status"]["containsSyntheticMedia"] = True
            request = api.videos().insert(part="snippet,status", notifySubscribers=True, body=body,
                media_body=MediaFileUpload(record["video"], mimetype="video/mp4", chunksize=8*1024*1024, resumable=True))
            record["stage"] = "uploading"
            save(path, journal)
            response = None
            while response is None:
                progress, response = request.next_chunk()
                if progress:
                    print(key, f"{progress.progress():.0%}", flush=True)
            record["new_id"] = response["id"]
            record["stage"] = "video_uploaded"
            save(path, journal)
        new_id = record["new_id"]
        current = video(api, new_id)
        require(current["status"]["privacyStatus"] == "private" and not current["status"].get("publishAt"),
                "Replacement already scheduled or public; review activation journal.")
        if not record.get("thumbnail_uploaded"):
            set_thumbnail(api, new_id, Path(record["thumbnail"]))
            record["thumbnail_uploaded"] = True
            save(path, journal)
        existing = api.captions().list(part="snippet", videoId=new_id).execute().get("items", [])
        for caption in record["captions"]:
            caption["name"] = (caption.get("name") or "").strip() or caption["language"]
            save(path, journal)
            if not any(item["snippet"].get("language") == caption["language"] and
                       item["snippet"].get("name", "") == caption["name"] for item in existing):
                api.captions().insert(part="snippet", body={"snippet": {
                    "videoId": new_id, "language": caption["language"], "name": caption["name"],
                    "isDraft": False}},
                    media_body=MediaFileUpload(caption["path"], mimetype="application/octet-stream")).execute()
        for playlist in record["playlists"]:
            add_to_playlist(api, playlist, new_id)
        record["stage"] = "uploaded"
        save(path, journal)
        print("UPLOADED PRIVATE", key, f"https://youtu.be/{new_id}", flush=True)
    print("Uploads complete. Review videos and end screens/cards in Studio, then run --activate.")


def writable_status(item, publish=None):
    result = {name: item["status"][name] for name in STATUS_KEYS if name in item["status"]}
    result["privacyStatus"] = "private"
    if publish:
        result["publishAt"] = publish
    return result


def set_schedule(api, item, publish=None):
    return api.videos().update(part="status", body={"id": item["id"],
        "status": writable_status(item, publish)}).execute()


def wait_schedule(api, identity, publish=None):
    """YouTube list responses can briefly lag behind a successful update."""
    for attempt in range(20):
        current = video(api, identity)
        status = current["status"]
        observed = status.get("publishAt")
        correct_time = (not observed) if publish is None else (
            bool(observed) and moment(observed) == moment(publish))
        if status["privacyStatus"] == "private" and correct_time:
            return current
        if attempt < 19:
            time.sleep(2)
    raise RuntimeError(f"YouTube has not confirmed schedule for {identity}: {observed!r}. "
                       "Progress saved; rerun --activate. Do not rerun --upload.")


def activate(api, journal, path, repo):
    require(set(journal["records"]) == set(TARGETS), "Incomplete batch.")
    for key, record in journal["records"].items():
        require(record.get("new_id") and record["stage"] in ("uploaded", "activating", "active"),
                f"Upload incomplete: {key}")
        future(record["publish_at"])
        current = video(api, record["new_id"])
        require(current["status"]["privacyStatus"] == "private", f"Replacement no longer private: {key}")
        require(current.get("processingDetails", {}).get("processingStatus") == "succeeded", f"Still processing: {key}")
        require(current["snippet"]["title"] == record["original"]["snippet"]["title"], f"Replacement title changed for {key}: YouTube={current['snippet']['title']!a}; saved={record['original']['snippet']['title']!a}")
        require(current["snippet"]["description"] == record["original"]["snippet"]["description"], "Replacement description changed.")
        require(current["snippet"].get("defaultAudioLanguage") == key.split("|")[1], "Wrong audio language.")
        publish = current["status"].get("publishAt")
        require(not publish or moment(publish) == moment(record["publish_at"]), "Replacement schedule changed.")
        check_old(video(api, record["old_id"]), key, retiring=record["stage"] in ("activating", "active"))
        tracks = api.captions().list(part="snippet", videoId=record["new_id"]).execute().get("items", [])
        for caption in record["captions"]:
            require(any(track["snippet"].get("language") == caption["language"] and
                        track["snippet"].get("name", "") == caption["name"] and
                        track["snippet"].get("status") == "serving" for track in tracks), "Replacement captions not ready.")
        for playlist in record["playlists"]:
            require(api.playlistItems().list(part="id", playlistId=playlist, videoId=record["new_id"], maxResults=1).execute().get("items"),
                    "Replacement playlist membership missing.")
    for key, record in journal["records"].items():
        new = video(api, record["new_id"])
        old = video(api, record["old_id"])
        if record["stage"] != "active":
            future(record["publish_at"])
            record["stage"] = "activating"
            save(path, journal)
            # Schedule verified new copy first. If retiring old fails, rerun --activate.
            set_schedule(api, new, record["publish_at"])
            confirmed = wait_schedule(api, record["new_id"], record["publish_at"])
            try:
                set_schedule(api, old)
            except Exception:
                # If the old schedule remains, undo the new schedule to avoid duplicates.
                observed = video(api, record["old_id"])
                if observed["status"].get("publishAt"):
                    set_schedule(api, confirmed)
                    wait_schedule(api, record["new_id"])
                    record["stage"] = "uploaded"
                    save(path, journal)
                    raise RuntimeError(f"Could not retire original {key}; replacement schedule rolled back. Original remains scheduled.")
                # A successful update can have a lost response; verify below.
            wait_schedule(api, record["old_id"])
            record["stage"] = "active"
            save(path, journal)
        ledger_path = repo / "backend/studio/work/youtube_release_state.json"
        backup = path.parent / "youtube_release_state.before-hook-replacements.json"
        if not backup.exists():
            backup.write_bytes(ledger_path.read_bytes())
        ledger = json.loads(ledger_path.read_text())
        entry = ledger["uploads"][key]
        require(entry["video_id"] in (record["old_id"], record["new_id"]), "Release ledger changed unexpectedly.")
        entry.update(video_id=record["new_id"], replaced_video_id=record["old_id"],
                     scheduled_publish_at=record["publish_at"], status="uploaded",
                     captions_uploaded=True, thumbnail_uploaded=True, end_screen_status="manual_required")
        save(ledger_path, ledger)
        print("ACTIVE", key, record["publish_at"], f"https://youtu.be/{record['new_id']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "upload", "activate"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--studio", type=Path, default=Path("E:/Documents/pp/topspot-backend-studio"))
    args = parser.parse_args()
    repo = Path.cwd()
    require((repo / "backend/studio/work/youtube_release_state.json").is_file(), "Run from topspot-youtube-scheduler.")
    path = repo / "backend/studio/work/hook_replacements_20260930/state.json"
    journal = json.loads(path.read_text()) if path.exists() else {"channel": CHANNEL, "records": {}}
    require(journal.get("channel") == CHANNEL, "Unexpected journal channel.")
    api = connect(repo)
    if args.prepare:
        prepare(api, args.studio.resolve(), journal, path)
    elif args.upload:
        upload(api, journal, path)
    else:
        activate(api, journal, path, repo)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"STOP: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
