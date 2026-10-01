"""Create and approve TopSpot40 teaser batches; publishing is always explicit.

Install beside topspot_tiktok_teaser_factory.py and topspot_tiktok_publisher.py.
plan: refresh public YouTube backlog, oldest first.
render: all three languages, reusing unchanged outputs.
approve: record Gary's review against all three current video hashes.
schedule: submit an approved story to all three accounts at an explicit time.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

LANGS = ("en", "es", "pt-BR")
ACCOUNTS = {
    "en": ("topspot40_en", "topspot40"),
    "es": ("topspot40_es", "topspot40es"),
    "pt-BR": ("topspot40_br", "topspot40br"),
}
FAB = "fabulous_fifties"
FAB_TITLES = {
    "en": "The Fabulous Fifties",
    "es": "Los fabulosos años cincuenta",
    "pt-BR": "Os fabulosos anos cinquenta",
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def fingerprint(path):
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ], check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


class Batch:
    def __init__(self, args):
        self.args = args
        self.repo = Path(__file__).resolve().parent
        self.work = args.work_root
        self.root = args.output_root
        self.config_path = self.root / "_shared/batch_config.json"
        self.state_path = self.root / "_shared/batch_state.json"
        self.queue_path = self.root / "publishing_queue.json"
        self.config = read(self.config_path, {"schema_version": 1, "stories": {}})
        self.state = read(self.state_path, {"schema_version": 1, "renders": {}})
        self.queue = read(self.queue_path)
        if not self.queue:
            raise RuntimeError("Existing publishing_queue.json is required")
        # Gary verified six seconds independently for all three documentaries.
        # Store the source fingerprints once, so future replacements require rechecking.
        if FAB not in self.config["stories"]:
            sources = {lang: fingerprint(self.documentary(FAB, lang)) for lang in LANGS}
            self.config["stories"][FAB] = {
                "titles": FAB_TITLES,
                "starts": {lang: 6.0 for lang in LANGS},
                "timing_sources": sources,
                "timing_verified": "Gary verified all three start times in chat on 2026-09-30",
            }
            write(self.config_path, self.config)

    def documentary(self, slug, lang):
        return self.work / slug / "factory/delivery" / lang / "documentary.mp4"

    def files(self, slug, lang):
        folder = self.root / slug
        return (folder / f"{slug}_{lang}_tiktok_preview.mp4",
                folder / f"{slug}_{lang}_review.json")

    def catalog(self):
        if self.args.action == "render":
            cached = read(self.root / "_shared/public_backlog.json")
            if not cached or not isinstance(cached.get("stories"), list):
                raise RuntimeError("No saved backlog; run plan once when YouTube quota is available")
            print(f"RENDER FROM SAVED BACKLOG: {cached.get('checked_at', 'unknown date')}")
            print("Preview creation only. Publisher will recheck YouTube before submission.")
            return cached["stories"]
        from topspot_hook_replacements import connect
        uploads = read(self.repo / "backend/studio/work/youtube_release_state.json")["uploads"]
        ids = sorted({r["video_id"] for r in uploads.values()
                      if isinstance(r, dict) and r.get("video_id")})
        api = connect(self.repo)
        videos = {}
        for offset in range(0, len(ids), 50):
            response = api.videos().list(part="snippet,status",
                                         id=",".join(ids[offset:offset + 50])).execute()
            videos.update({v["id"]: v for v in response.get("items", [])})
        stories = []
        for slug in sorted({key.rsplit("|", 1)[0] for key in uploads}):
            versions = {}
            for lang in LANGS:
                video = videos.get(uploads.get(f"{slug}|{lang}", {}).get("video_id"))
                if not video or video.get("status", {}).get("privacyStatus") != "public":
                    break
                published = video["snippet"]["publishedAt"]
                if datetime.fromisoformat(published.replace("Z", "+00:00")) > datetime.now(timezone.utc):
                    break
                versions[lang] = {
                    "video_id": video["id"], "published_at": published,
                    "title": video["snippet"]["title"].split("|", 1)[0].strip(),
                }
            if len(versions) == 3:
                stories.append({"slug": slug, "versions": versions,
                                "oldest": min(v["published_at"] for v in versions.values())})
        stories.sort(key=lambda s: (s["oldest"], s["slug"]))
        write(self.root / "_shared/public_backlog.json", {
            "checked_at": timestamp(), "source": "youtube_release_state.json",
            "stories": stories,
        })
        return stories

    def specs(self, story):
        slug = story["slug"]
        factory = self.work / slug / "factory"
        opening = factory / "shared/opening.mp4"
        config = self.config["stories"].get(slug, {})
        if not opening.is_file() and any(lang not in config.get("starts", {}) for lang in LANGS):
            if getattr(self.args, "action", "render") == "render":
                config = self.detect_timing(slug)
        specs = {}
        for lang in LANGS:
            doc = self.documentary(slug, lang)
            hook = factory / "delivery" / lang / "narration/hook.mp3"
            ending = self.root / "_shared/endings" / f"ending_{lang}.mp3"
            for path in (doc, hook, ending):
                if not path.is_file():
                    raise RuntimeError(f"Missing {path}")
            start = config.get("starts", {}).get(lang)
            if start is not None:
                if config.get("timing_sources", {}).get(lang) != fingerprint(doc):
                    raise RuntimeError(f"{slug}/{lang}: documentary changed; recheck timing")
            elif opening.is_file():
                start = duration(opening)
            else:
                raise RuntimeError(f"{slug}/{lang}: hook start time needs verification")
            if not 0 <= float(start) < float("inf"):
                raise RuntimeError("Invalid start time")
            title = config.get("titles", {}).get(lang) or story["versions"][lang]["title"]
            inputs = [doc, hook, ending, self.repo / "topspot_tiktok_teaser_factory.py"]
            if opening.is_file():
                inputs.append(opening)
            specs[lang] = {
                "start": float(start), "title": title, "ending": str(ending),
                "documentary": str(doc), "inputs": [fingerprint(p) for p in inputs],
                "youtube_id": story["versions"][lang]["video_id"],
            }
        return specs

    def detect_timing(self, slug):
        from topspot_tiktok_hook_timing import find_hook
        config = dict(self.config["stories"].get(slug, {}))
        starts = dict(config.get("starts", {}))
        sources = dict(config.get("timing_sources", {}))
        evidence = dict(config.get("audio_match_evidence", {}))
        for lang in LANGS:
            doc = self.documentary(slug, lang)
            hook = self.work / slug / "factory/delivery" / lang / "narration/hook.mp3"
            if lang in starts and sources.get(lang) == fingerprint(doc):
                continue
            if not doc.is_file() or not hook.is_file():
                raise RuntimeError(f"{slug}/{lang}: missing hook or documentary")
            print(f"MATCH AUDIO {slug}/{lang}", flush=True)
            result = find_hook(doc, hook)
            starts[lang] = result["start_seconds"]
            sources[lang] = fingerprint(doc)
            evidence[lang] = result
            print(f"  Hook starts at {starts[lang]:.3f}s; matches agree", flush=True)
        config.update(starts=starts, timing_sources=sources, audio_match_evidence=evidence,
                      timing_verified="automatic audio match; previews still require review")
        self.config["stories"][slug] = config
        write(self.config_path, self.config)
        return config

    def plan(self, stories):
        for story in stories:
            slug = story["slug"]
            jobs = [j for j in self.queue["jobs"] if j["slug"] == slug]
            if slug == "george_martin":
                status = "already posted manually"
            elif len(jobs) == 3:
                status = ", ".join(f"{j['language']}={j['status']}" for j in jobs)
            else:
                try:
                    self.specs(story)
                    status = "ready to render/review"
                except RuntimeError as error:
                    status = str(error)
            print(f"{story['oldest'][:10]} | {slug} | {status}")

    def render(self, stories):
        targets = [s for s in stories if s["slug"] == self.args.slug] if self.args.slug else stories
        count = 0
        for story in targets:
            slug = story["slug"]
            if slug == "george_martin" or any(j["slug"] == slug for j in self.queue["jobs"]):
                print(f"SKIP {slug}: already recorded/posted")
                continue
            try:
                specs = self.specs(story)
            except RuntimeError as error:
                print(f"HOLD {error}")
                if self.args.slug:
                    raise
                continue
            for lang in LANGS:
                spec = specs[lang]
                video, review_path = self.files(slug, lang)
                key = f"{slug}|{lang}"
                existing = self.state["renders"].get(key)
                review = read(review_path, {})
                reuse = bool(existing and existing["spec"] == spec and
                             video.is_file() and review_path.is_file() and
                             digest(video) == existing["video_sha256"] and
                             digest(review_path) == existing["review_sha256"])
                # Adopt only the just-reviewed Fabulous Fifties outputs in this session.
                if not existing and slug == FAB and video.is_file() and review_path.is_file():
                    reuse = (review.get("slug") == slug and review.get("language") == lang
                             and review.get("title") == spec["title"]
                             and review.get("start_seconds") == spec["start"]
                             and Path(review.get("source_documentary", "")).resolve()
                             == Path(spec["documentary"]).resolve()
                             and Path(review.get("ending_audio", "")).resolve()
                             == Path(spec["ending"]).resolve())
                if reuse:
                    print(f"REUSE {key}")
                else:
                    subprocess.run([
                        sys.executable, str(self.repo / "topspot_tiktok_teaser_factory.py"),
                        "--work-root", str(self.work), "--slug", slug, "--language", lang,
                        "--output-root", str(self.root), "--title", spec["title"],
                        "--start-seconds", str(spec["start"]), "--ending-audio", spec["ending"],
                        "--youtube-url", "https://www.youtube.com/watch?v=" + spec["youtube_id"],
                    ], check=True)
                self.state["renders"][key] = {
                    "spec": spec, "video_sha256": digest(video),
                    "review_sha256": digest(review_path), "recorded_at": timestamp(),
                }
                write(self.state_path, self.state)
            print(f"REVIEW ALL THREE: {self.root / slug}")
            count += 1
            if count >= self.args.limit:
                break
        if self.args.slug and not targets:
            raise RuntimeError("Story is not public in all three release records")
        print("No uploads or approvals performed.")

    def approve(self, stories):
        story = next((s for s in stories if s["slug"] == self.args.slug), None)
        if not story:
            raise RuntimeError("Approval requires a story public in all three languages")
        specs = self.specs(story)
        additions = []
        for lang in LANGS:
            key = f"{story['slug']}|{lang}"
            existing_job = next((j for j in self.queue["jobs"] if j["id"] == key), None)
            if existing_job:
                raise RuntimeError(f"{key} already in queue; approval will not overwrite it")
            video, review_path = self.files(story["slug"], lang)
            record = self.state["renders"].get(key)
            if not record or record["spec"] != specs[lang]:
                raise RuntimeError(f"{key}: run render first to record current inputs")
            if digest(video) != record["video_sha256"] or digest(review_path) != record["review_sha256"]:
                raise RuntimeError(f"{key}: output changed; render/review again")
            profile, handle = ACCOUNTS[lang]
            additions.append({
                "id": key, "slug": story["slug"], "language": lang,
                "story_order": 0, "profile": profile, "expected_tiktok_handle": handle,
                "video_file": str(video), "review_file": str(review_path),
                "sha256": record["video_sha256"], "title": specs[lang]["title"],
                "approval": "approved_by_Gary_in_chat", "approval_method": "explicit_batch_approve_command",
                "approved_at": timestamp(), "start_seconds": specs[lang]["start"],
                "youtube_video_id": specs[lang]["youtube_id"],
                "youtube_url": "https://www.youtube.com/watch?v=" + specs[lang]["youtube_id"],
                "scheduled_at": None, "upload_request_id": None, "status": "pending_preflight",
            })
        self.queue["jobs"].extend(additions)
        order = [s["slug"] for s in stories]
        order.extend(slug for slug in self.queue.get("story_order", []) if slug not in order)
        self.queue["story_order"] = order
        for job in self.queue["jobs"]:
            job["story_order"] = order.index(job["slug"]) + 1
        write(self.queue_path, self.queue)
        print(f"Approved and queued all three: {story['slug']}. No uploads performed.")

    def schedule(self):
        from topspot_tiktok_publisher import parse_time
        if not self.args.at or not self.args.confirm_not_posted:
            raise RuntimeError("Scheduling requires --at and --confirm-not-posted")
        chosen_time = parse_time(self.args.at)
        if chosen_time <= datetime.now(timezone.utc):
            raise RuntimeError("Scheduled time must be in the future")
        jobs = [j for j in self.queue["jobs"] if j["slug"] == self.args.slug]
        if len(jobs) != 3 or {j["language"] for j in jobs} != set(LANGS):
            raise RuntimeError("All three approved jobs must be in the queue")
        if any(j.get("approval") != "approved_by_Gary_in_chat" for j in jobs):
            raise RuntimeError("All three jobs require approval")
        # Keep one story per account per publishing day. Interpret the day in the
        # offset chosen for this schedule, rather than comparing UTC dates.
        for other in self.queue["jobs"]:
            if other["slug"] == self.args.slug or not other.get("upload_request_id"):
                continue
            reserved = other.get("scheduled_at") or other.get("submission_started_at")
            if reserved and parse_time(reserved).astimezone(chosen_time.tzinfo).date() == chosen_time.date():
                raise RuntimeError(f"Publishing day already used by {other['id']}; choose another day")
        for lang in LANGS:
            job = next(j for j in jobs if j["language"] == lang)
            if job.get("upload_request_id"):
                print(f"SKIP {job['id']}: already submitted; use publisher status")
                continue
            subprocess.run([
                sys.executable, str(self.repo / "topspot_tiktok_publisher.py"),
                "publish", "--queue", str(self.queue_path), "--job", job["id"],
                "--at", self.args.at, "--confirm-not-posted",
            ], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "render", "approve", "schedule"))
    parser.add_argument("--slug")
    parser.add_argument("--limit", type=int, default=7, help="Maximum stories rendered per batch")
    parser.add_argument("--at", help="Explicit future ISO-8601 time with timezone offset")
    parser.add_argument("--confirm-not-posted", action="store_true")
    parser.add_argument("--work-root", type=Path, default=Path("E:/Documents/pp/topspot-backend-studio/backend/studio/work"))
    parser.add_argument("--output-root", type=Path, default=Path("E:/Documents/pp/topspot-tiktok-teasers"))
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.action in {"approve", "schedule"} and not args.slug:
        parser.error("--slug is required")
    args.output_root.mkdir(parents=True, exist_ok=True)
    lock = args.output_root / "publishing_queue.json.lock"
    if args.action == "schedule":
        # Child publisher processes acquire the shared queue lock themselves.
        controller_lock = args.output_root / "_batch_schedule.lock"
        descriptor = os.open(controller_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            Batch(args).schedule()
        finally:
            os.close(descriptor)
            controller_lock.unlink()
    else:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            batch = Batch(args)
            stories = batch.catalog()
            getattr(batch, args.action)(stories)
        finally:
            os.close(descriptor)
            lock.unlink()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"STOPPED: {error}", file=sys.stderr)
        sys.exit(1)
