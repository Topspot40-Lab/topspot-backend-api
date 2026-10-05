"""Separate LinkedIn video calendar. Default: local preview, no uploads.

Uses the existing TikTok publisher only for credentials, hashing, atomic saves,
and YouTube checks. Never modifies the TikTok queue or its calendar.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from topspot_tiktok_publisher import API, parse_time, refresh_youtube, save, sha256

ROOT = Path("E:/Documents/pp/topspot-tiktok-teasers")
PAGES = {
    "en": ("topspot40_en", "urn:li:organization:143948792", "TopSpot40 English"),
    "es": ("topspot40_es", "urn:li:organization:143948794", "TopSpot40 Español"),
    "pt-BR": ("topspot40_br", "urn:li:organization:143967944", "TopSpot40 Português"),
}
CTA = {
    "en": "Watch the full story on the TopSpot40 YouTube channel. Explore more music stories at https://topspot40.com",
    "es": "Mira la historia completa en español en el canal de YouTube de TopSpot40. Explora más historias musicales en https://topspot40.com",
    "pt-BR": "Assista à história completa em português no canal do TopSpot40 no YouTube. Explore mais histórias musicais em https://topspot40.com",
}
CONTEXT = {
    "en": "Music history offers stories to enjoy, discuss, and share across generations. Explore this short preview from TopSpot40.",
    "es": "La historia de la música ofrece relatos para disfrutar, conversar y compartir entre generaciones. Descubre este breve adelanto de TopSpot40.",
    "pt-BR": "A história da música traz relatos para apreciar, conversar e compartilhar entre gerações. Conheça esta breve prévia do TopSpot40.",
}

TAGS = {"en": "#MusicHistory", "es": "#HistoriaDeLaMusica", "pt-BR": "#HistoriaDaMusica"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def utcnow():
    return datetime.now(timezone.utc)


def provider_time(value):
    """Schedule API dates are UTC, including responses without an offset."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def prepare(path, start):
    require(not path.exists(), "LinkedIn queue already exists; use preview, never overwrite it")
    source = load(ROOT / "publishing_queue.json")
    plan = load(ROOT / "_shared/publishing_calendar.json")
    lookup = {j["id"]: j for j in source["jobs"]}
    require(len(lookup) == len(source["jobs"]), "Duplicate source job IDs")
    first = parse_time(start)
    require(first > utcnow(), "Start time must be in the future")
    jobs, slugs, used = [], set(), set()
    for entry in sorted(plan["entries"], key=lambda e: parse_time(e["planned_publish_at"])):
        if entry["slug"] == "george_martin":
            continue
        require(entry["slug"] not in slugs, "Repeated calendar story")
        slugs.add(entry["slug"])
        at = first + timedelta(days=len(slugs) - 1)
        group = [lookup[item["id"]] for item in entry["jobs"]]
        require(len(group) == 3 and {j["language"] for j in group} == set(PAGES),
                "Each story must have exactly EN, ES and PT-BR")
        for item in entry["jobs"]:
            original = lookup[item["id"]]
            lang = original["language"]
            profile, page_id, page_name = PAGES[lang]
            require(original["id"] not in used, "Repeated job in source calendar")
            used.add(original["id"])
            require(original["slug"] == entry["slug"] and original["profile"] == item["profile"] == profile,
                    "Source story/profile mismatch")
            require(original.get("approval") == "approved_by_Gary_in_chat", "Missing original approval")
            require(original["sha256"] == item["sha256"] == sha256(original["video_file"]),
                    "Approved video changed: " + original["id"])
            fields = ("id", "slug", "language", "profile", "title", "video_file", "sha256",
                      "approval", "youtube_video_id", "youtube_url", "story_order")
            job = {key: original[key] for key in fields}
            caption = job["title"] + "\n\n" + CONTEXT[lang] + "\n\n" + CTA[lang] + "\n\n" + job["youtube_url"]
            caption += "\n\n#TopSpot40 " + TAGS[lang]
            job.update(page_id=page_id, page_name=page_name, caption=caption,
                       scheduled_at=at.isoformat(), status="pending",
                       external_id="topspot40:linkedin:" + job["id"])
            jobs.append(job)
    require(jobs, "No calendar jobs found")
    save(path, {"version": 1, "platform": "linkedin", "start": start,
                "excluded_already_posted": ["george_martin"], "jobs": jobs})
    print("Created separate LinkedIn queue:", path)


def validate(queue):
    require(queue.get("platform") == "linkedin" and queue.get("version") == 1, "Wrong queue")
    used, dates = set(), {}
    for j in queue["jobs"]:
        require(j["id"] not in used, "Duplicate queue job")
        used.add(j["id"])
        require(j["id"] == j["slug"] + "|" + j["language"], "Job identity mismatch")
        require(j["slug"] != "george_martin", "George Martin is already posted")
        require((j["profile"], j["page_id"], j["page_name"]) == PAGES[j["language"]], "Page mapping changed")
        require(j["external_id"] == "topspot40:linkedin:" + j["id"], "External ID changed")
        require(j.get("approval") == "approved_by_Gary_in_chat", "Missing approval")
        at = parse_time(j["scheduled_at"])
        key = (at.date(), j["profile"])
        require(key not in dates, "More than one post per Page/day")
        dates[key] = j["slug"]
        require(j["caption"] and len(j["caption"]) <= 2200, "Caption missing or too long")
    groups = {}
    for j in queue["jobs"]:
        groups.setdefault((j["slug"], j["scheduled_at"]), []).append(j["language"])
    require(all(len(v) == 3 and set(v) == set(PAGES) for v in groups.values()), "Incomplete language group")


def preview(queue):
    validate(queue)
    print("LINKEDIN ONLY:", len(queue["jobs"]), "videos")
    print("Statuses:", dict(Counter(j["status"] for j in queue["jobs"])))
    for j in queue["jobs"]:
        if j["language"] == "en":
            print(j["scheduled_at"], j["slug"], "EN / ES / PT-BR")
    print("\nDestinations:")
    for profile, page_id, name in PAGES.values():
        print(profile, "->", name, page_id)
    print("\nFirst story captions:")
    for j in queue["jobs"][:3]:
        print("\n" + j["language"] + ":\n" + j["caption"])


def provider_records(api, profile):
    records = []
    for page in range(1, 101):
        data = api.get("/api/uploadposts/history", profile_username=profile,
                       platform="linkedin", page=page, limit=100)
        require(isinstance(data.get("history"), list), "Unexpected history response")
        records.extend(data["history"])
        records.extend(data.get("in_progress") or [])
        if len(data["history"]) < 100:
            break
    else:
        raise RuntimeError("History scan limit exceeded")
    scheduled = api.get("/api/uploadposts/schedule", profile_username=profile)
    require(isinstance(scheduled.get("scheduled_posts"), list), "Unexpected schedule response")
    rows = scheduled["scheduled_posts"]
    require(scheduled.get("total", len(rows)) <= len(rows), "Incomplete schedule response")
    records.extend(r for r in rows if "linkedin" in (r.get("platforms") or []))
    return records, rows


def preflight(queue, api):
    validate(queue)
    pending = [j for j in queue["jobs"] if j["status"] == "pending"]
    require(not any(j["status"] in {"submitting", "submission_unknown", "needs_review"}
                    for j in queue["jobs"]), "Uncertain submission exists; run status and inspect before resuming")
    for profile, page_id, name in PAGES.values():
        pin = api.get("/api/uploadposts/users/linkedin-page", profile_username=profile)
        require(str(pin.get("selected_page_id")) == page_id, "Pinned Page mismatch: " + profile)
        require(any(str(p.get("id")) == page_id for p in pin.get("pages", [])), "Page unavailable: " + name)
    histories = {profile: provider_records(api, profile)[0] for profile, _, _ in PAGES.values()}
    if pending:
        checked = {"jobs": [dict(j) for j in pending]}
        refresh_youtube(checked)
        require(all(j.get("youtube_public") for j in checked["jobs"]), "A source documentary is not public on YouTube")
    for j in pending:
        require(parse_time(j["scheduled_at"]) > utcnow() + timedelta(minutes=5), "Schedule too near or in past: " + j["id"])
        require(sha256(j["video_file"]) == j["sha256"], "Video changed: " + j["id"])
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                                "-of", "json", j["video_file"]], check=True, capture_output=True, text=True)
        media = json.loads(probe.stdout)
        videos = [s for s in media["streams"] if s["codec_type"] == "video"]
        require(len(videos) == 1 and abs(videos[0]["width"] / videos[0]["height"] - 9 / 16) < .01,
                "Expected vertical video: " + j["id"])
        require(any(s["codec_type"] == "audio" for s in media["streams"]), "Video has no audio: " + j["id"])
        require(3 <= float(media["format"]["duration"]) <= 90, "Expected approved short teaser: " + j["id"])
        for r in histories[j["profile"]]:
            text = " ".join(str(r.get(k) or "") for k in ("title", "post_title", "post_caption", "caption", "description"))
            match = (r.get("external_id") == j["external_id"] or
                     r.get("source_filename") == Path(j["video_file"]).name or
                     j["title"].casefold() in text.casefold())
            require(not match, "Possible existing LinkedIn post/schedule: " + j["id"])
    print("PREFLIGHT PASSED:", len(pending), "pending LinkedIn videos; no uploads made", flush=True)


def submit(queue, path, api, limit):
    preflight(queue, api)
    pending = [j for j in queue["jobs"] if j["status"] == "pending"]
    if limit:
        pending = pending[:limit]
    for j in pending:
        require(parse_time(j["scheduled_at"]) > utcnow() + timedelta(minutes=5), "Scheduled time too near")
        pin = api.get("/api/uploadposts/users/linkedin-page", profile_username=j["profile"])
        require(str(pin.get("selected_page_id")) == j["page_id"], "Pinned Page changed")
        require(sha256(j["video_file"]) == j["sha256"], "Video changed")
        identity = j["external_id"] + ":" + j["page_id"] + ":" + j["sha256"]
        token = "ts40-li-" + hashlib.sha256(identity.encode()).hexdigest()
        j.update(idempotency_key=token, upload_request_id=token, status="submitting")
        save(path, queue)
        print("SCHEDULE:", j["id"], j["scheduled_at"], flush=True)
        fields = {"user": j["profile"], "platform[]": "linkedin", "title": j["title"],
                  "linkedin_description": j["caption"],
                  "target_linkedin_page_id": j["page_id"].rsplit(":", 1)[-1],
                  "visibility": "PUBLIC", "async_upload": "true",
                  "scheduled_date": parse_time(j["scheduled_at"]).astimezone(timezone.utc).isoformat(),
                  "external_id": j["external_id"], "request_id": token}
        try:
            response = api.upload(j, fields)
            j["provider_upload_response"] = response
            if response.get("request_id"):
                j["upload_request_id"] = response["request_id"]
            j["provider_job_id"] = response.get("job_id")
            j["status"] = "submitted" if response.get("success") is not False and response.get("job_id") else "needs_review"
            save(path, queue)
            require(j["status"] == "submitted", "Provider response needs review; do not resend")
        except BaseException:
            if j["status"] == "submitting":
                j["status"] = "submission_unknown"
            save(path, queue)
            raise
    print("Submission pass finished. Run status to verify provider dates and IDs.")


def status(queue, path, api):
    validate(queue)
    schedules = {}
    for profile, _, _ in PAGES.values():
        _, rows = provider_records(api, profile)
        schedules[profile] = [r for r in rows if "linkedin" in (r.get("platforms") or [])]
    verified = 0
    for j in queue["jobs"]:
        if j["status"] == "pending":
            continue
        rows = [r for r in schedules[j["profile"]] if r.get("external_id") == j["external_id"]]
        if rows:
            require(len(rows) == 1, "Duplicate provider external ID")
            r = rows[0]
            require(provider_time(r["scheduled_date"]) == parse_time(j["scheduled_at"]), "Provider date mismatch")
            require(r.get("profile_username") == j["profile"] and r.get("platforms") == ["linkedin"], "Provider destination mismatch")
            require(r.get("job_id") and j.get("provider_job_id") in (None, r["job_id"]), "Provider job ID mismatch")
            j.update(provider_job_id=r["job_id"], status="scheduled_verified", verified_at=utcnow().isoformat())
            verified += 1
        else:
            data = api.get("/api/uploadposts/history", external_id=j["external_id"],
                           platform="linkedin", profile_username=j["profile"], limit=10)
            good = [r for r in data.get("history", []) if r.get("success") is True and str(r.get("post_url") or "").startswith("https://")]
            if len(good) == 1:
                j.update(status="published", post_url=good[0]["post_url"])
            else:
                print("NEEDS REVIEW:", j["id"], "not found as scheduled or published")
                j["status"] = "needs_review"
        save(path, queue)
        print(j["id"], j["status"], j.get("post_url") or j.get("provider_job_id"))
    print("Verified future LinkedIn jobs:", verified)
    print("Statuses:", dict(Counter(j["status"] for j in queue["jobs"])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("prepare", "preview", "preflight", "submit", "status"), default="preview")
    parser.add_argument("--start", default="2026-10-06T12:00:00-05:00")
    parser.add_argument("--queue", type=Path, default=ROOT / "linkedin_publishing_queue.json")
    parser.add_argument("--limit", type=int, default=0, help="Submission limit; 0 means all pending")
    args = parser.parse_args()
    require(args.limit >= 0, "Limit cannot be negative")
    lock = Path(str(args.queue) + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        if args.action == "prepare":
            prepare(args.queue, args.start)
        queue = load(args.queue)
        if args.action in {"prepare", "preview"}:
            preview(queue)
            print("\nNo videos uploaded or scheduled.")
        elif args.action == "preflight":
            preflight(queue, API())
        elif args.action == "submit":
            submit(queue, args.queue, API(), args.limit)
        else:
            status(queue, args.queue, API())
    finally:
        os.close(fd)
        lock.unlink()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("STOPPED:", error, file=sys.stderr)
        sys.exit(1)
