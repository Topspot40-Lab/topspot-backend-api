"""TopSpot40 queue publisher. Default action is preflight; never posts by default.

Place beside topspot_hook_replacements.py in topspot-youtube-scheduler.
Key: TOPSPOT_UPLOAD_POST_KEY environment variable, or a hidden interactive prompt.
Credentials are never written to disk. Queue data belongs outside the git repo.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

BASE = "https://api.upload-post.com"
ACCOUNTS = {
    "en": ("topspot40_en", "topspot40"),
    "es": ("topspot40_es", "topspot40es"),
    "pt-BR": ("topspot40_br", "topspot40br"),
}
UNSENT = {"pending_preflight", "held_for_youtube",
          "awaiting_account_and_duplicate_check", "ready_for_review", "blocked"}
CTA = {
    "en": "Watch the full story on YouTube: TopSpot40. Explore TopSpot40.com.",
    "es": "Mira la historia completa en YouTube: TopSpot40. Visita TopSpot40.com.",
    "pt-BR": "Assista à história completa no YouTube: TopSpot40. Visite TopSpot40.com.",
}


def now():
    return datetime.now(timezone.utc)


def parse_time(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Date/time must include an offset, such as -05:00.")
    return value


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, data):
    data["updated_at"] = now().isoformat()
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class API:
    def __init__(self):
        try:
            import requests
        except ImportError:
            raise RuntimeError("Install dependency: python -m pip install requests")
        self.requests = requests
        key = os.environ.get("TOPSPOT_UPLOAD_POST_KEY")
        if not key:
            from keyring.backends.Windows import WinVaultKeyring
            key = WinVaultKeyring().get_password("TopSpot40.UploadPost", "factory")
        if not key:
            raise RuntimeError("Upload-Post key not found in Windows Credential Manager.")
        if not key.strip():
            raise RuntimeError("API key is empty.")
        self.headers = {"Authorization": "Apikey " + key.strip()}

    def get(self, endpoint, **params):
        response = self.requests.get(BASE + endpoint, headers=self.headers,
                                     params=params, timeout=(15, 60))
        if not response.ok:
            raise RuntimeError(f"GET {endpoint}: HTTP {response.status_code}")
        data = response.json()
        if data.get("success") is False:
            raise RuntimeError(f"GET {endpoint}: provider rejected request")
        return data

    def upload(self, job, fields):
        headers = dict(self.headers, **{"Idempotency-Key": job["idempotency_key"]})
        with Path(job["video_file"]).open("rb") as stream:
            response = self.requests.post(
                BASE + "/api/upload", headers=headers, data=fields,
                files={"video": (Path(job["video_file"]).name, stream, "video/mp4")},
                timeout=(300, 600))
        if not response.ok:
            # Even HTTP errors can follow a partial upload. Never blindly retry.
            raise RuntimeError(f"Upload returned HTTP {response.status_code}; reconcile first")
        return response.json()


def history(api, profile):
    rows = []
    for page in range(1, 101):
        data = api.get("/api/uploadposts/history", profile_username=profile,
                       platform="tiktok", limit=100, page=page)
        batch = data.get("history")
        if not isinstance(batch, list):
            raise RuntimeError("Unexpected history response; stopping")
        rows.extend(batch)
        rows.extend(data.get("in_progress") or [])
        if len(batch) < 100:
            return rows
    raise RuntimeError("History exceeds scan limit; stopping")


def refresh_youtube(queue):
    from topspot_hook_replacements import connect
    ids = sorted({j["youtube_video_id"] for j in queue["jobs"]
                  if j.get("youtube_video_id")})
    videos = {}
    api = connect(Path(__file__).resolve().parent)
    for offset in range(0, len(ids), 50):
        result = api.videos().list(part="snippet,status",
                                  id=",".join(ids[offset:offset + 50])).execute()
        videos.update({v["id"]: v for v in result.get("items", [])})
    for job in queue["jobs"]:
        video = videos.get(job.get("youtube_video_id"), {})
        privacy = video.get("status", {}).get("privacyStatus")
        published = video.get("snippet", {}).get("publishedAt")
        job.update(youtube_privacy=privacy, youtube_published_at=published,
                   youtube_checked_at=now().isoformat(), youtube_public=False)
        if privacy == "public" and published:
            job["youtube_public"] = parse_time(published) <= now()


def preflight(queue, api):
    refresh_youtube(queue)
    profiles = {p["username"]: p for p in
                api.get("/api/uploadposts/users").get("profiles", [])}
    settings, histories = {}, {}
    for profile, _ in ACCOUNTS.values():
        settings[profile] = api.get("/api/uploadposts/tiktok/settings", profile=profile)
        histories[profile] = history(api, profile)
    for job in queue["jobs"]:
        if job["status"] not in UNSENT:
            continue
        errors = []
        profile, handle = ACCOUNTS[job["language"]]
        account = profiles.get(profile, {}).get("social_accounts", {}).get("tiktok") or {}
        if job["profile"] != profile or job["expected_tiktok_handle"] != handle:
            errors.append("Queue account mapping was changed")
        if str(account.get("handle") or "").lstrip("@") != handle:
            errors.append("Connected TikTok handle does not match")
        if account.get("reauth_required"):
            errors.append("TikTok account requires reconnection")
        account_handle = str(account.get("handle") or "").lstrip("@")
        stable_id = account.get("username") or (
            "handle:" + account_handle if account_handle else None)
        job["tiktok_identity_source"] = "account_id" if account.get("username") else "handle"
        if not stable_id:
            errors.append("Provider did not return a TikTok identity")
        elif job.get("tiktok_account_id") not in (None, stable_id):
            errors.append("Connected TikTok account ID changed")
        elif not errors:
            job["tiktok_account_id"] = stable_id
        if "PUBLIC_TO_EVERYONE" not in settings[profile].get("privacy_level_options", []):
            errors.append("Account cannot publish publicly")
        if "video_privacy" not in (account.get("capabilities") or []):
            errors.append("Connection lacks video privacy capability")
        video = Path(job["video_file"])
        if not video.is_file() or sha256(video) != job["sha256"]:
            errors.append("Video missing or changed since approval")
        if job.get("approval") != "approved_by_Gary_in_chat":
            errors.append("Video has no recorded approval")
        if video.is_file():
            result = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video)
            ], capture_output=True, text=True, check=True)
            duration = float(result.stdout.strip())
            job["duration_seconds"] = duration
            maximum = settings[profile].get("max_video_post_duration_sec")
            if not maximum or not 3 <= duration <= float(maximum):
                errors.append("Duration outside account limits")
        caption = job["title"] + "\n\n" + CTA[job["language"]] + "\n#TopSpot40 #MusicHistory"
        if job.get("youtube_url"):
            caption += "\n" + job["youtube_url"]
        if len(caption) > 2200:
            errors.append("Caption exceeds TikTok limit")
        job["caption"] = caption
        job["publish_settings"] = {
            "privacy_level": "PUBLIC_TO_EVERYONE", "post_mode": "DIRECT_POST",
            "brand_organic_toggle": "true", "brand_content_toggle": "false",
            "is_aigc": "true", "disable_duet": "true", "disable_stitch": "true",
            "disable_comment": str(bool(settings[profile].get("comment_disabled"))).lower(),
            "cover_timestamp": "1000", "disable_inbox_fallback": "true",
        }
        # Title matching is a conservative check for older provider uploads.
        matches = [row for row in histories[profile] if
                   row.get("external_id") == "topspot40:" + job["id"] or
                   job["title"].casefold() in str(
                       row.get("post_title") or row.get("post_caption") or "").casefold()]
        if matches:
            errors.append("Possible existing Upload-Post upload; inspect history")
        job["provider_duplicate_candidates"] = [
            {k: row.get(k) for k in ("post_url", "platform_post_id", "success", "job_id")}
            for row in matches]
        job["preflight_errors"] = errors
        public = all(j.get("youtube_public") for j in queue["jobs"] if j["slug"] == job["slug"])
        job["status"] = "blocked" if errors else (
            "ready_for_review" if public else "held_for_youtube")
        job["preflight_at"] = now().isoformat()


def reconcile(queue, api):
    for job in queue["jobs"]:
        if not job.get("upload_request_id"):
            continue
        params = {"job_id": job["provider_job_id"]} if job.get("provider_job_id") else {
            "request_id": job["upload_request_id"]}
        try:
            data = api.get("/api/uploadposts/status", **params)
        except RuntimeError as error:
            job["reconcile_note"] = str(error)
            continue
        job["provider_status_response"] = data
        results = [r for r in data.get("results", []) if r.get("platform") == "tiktok"]
        if any(r.get("fallback_to_inbox") for r in results):
            job["status"] = "delivered_to_inbox"
        elif data.get("status") == "completed" and any(
                r.get("success") is True and not r.get("skipped") for r in results):
            job["status"] = "provider_completed"
        elif data.get("status") == "failed":
            job["status"] = "provider_failed_needs_review"
        elif data.get("status") in {"pending", "queued", "processing", "in_progress"}:
            job["status"] = "submitted"
        records = api.get("/api/uploadposts/history", external_id="topspot40:" + job["id"],
                          platform="tiktok", profile_username=job["profile"], limit=10)
        for row in records.get("history", []):
            if row.get("success") is True:
                job["provider_history_record"] = row
                if row.get("fallback_to_inbox"):
                    job["status"] = "delivered_to_inbox"
                elif str(row.get("post_url") or "").startswith("https://"):
                    job["status"] = "published"
                    job["post_url"] = row["post_url"]
                break


def publish(queue, path, api, args):
    if not args.job or not args.confirm_not_posted:
        raise RuntimeError("Publishing requires --job and --confirm-not-posted after checking TikTok")
    job = next((j for j in queue["jobs"] if j["id"] == args.job), None)
    if not job or job["status"] not in UNSENT:
        raise RuntimeError("Job absent or already submitted; use status, never resend")
    preflight(queue, api)
    save(path, queue)
    if job["status"] != "ready_for_review":
        raise RuntimeError(f"Job is {job['status']}: {job.get('preflight_errors')}")
    scheduled = None
    if args.at:
        scheduled = parse_time(args.at).astimezone(timezone.utc)
        if scheduled <= now():
            raise RuntimeError("Scheduled time must be in the future")
    identity = f"topspot40:{job['id']}:{job['sha256']}:{job['tiktok_account_id']}"
    token = "ts40-" + hashlib.sha256(identity.encode()).hexdigest()
    job.update(idempotency_key=token, upload_request_id=token,
               scheduled_at=scheduled.isoformat() if scheduled else None,
               status="submitting", submission_started_at=now().isoformat(),
               manual_duplicate_check_at=now().isoformat())
    fields = dict(job["publish_settings"], user=job["profile"],
                  **{"platform[]": "tiktok"}, title=job["caption"],
                  async_upload="true", external_id="topspot40:" + job["id"],
                  request_id=token)
    if scheduled:
        fields["scheduled_date"] = scheduled.isoformat()
    save(path, queue)  # Durable intent before making the external request.
    try:
        response = api.upload(job, fields)
        job["provider_upload_response"] = response
        if response.get("request_id"):
            job["upload_request_id"] = response["request_id"]
        if response.get("job_id"):
            job["provider_job_id"] = response["job_id"]
        job["status"] = "submitted" if response.get("success") is not False else "submission_needs_review"
    except BaseException:
        job["status"] = "submission_unknown"
        save(path, queue)
        raise
    save(path, queue)


def show(queue):
    for job in sorted(queue["jobs"], key=lambda j: (j["story_order"], j["language"])):
        print(f"{job['id']}: {job['status']} -> @{job['expected_tiktok_handle']}")
        for error in job.get("preflight_errors", []):
            print("  BLOCK:", error)
        if job.get("post_url"):
            print(" ", job["post_url"])
        if job["status"] == "ready_for_review":
            print("  Caption:", job["caption"].replace("\n", " | "))
    print("\nSettings: public; AI label; own-business promotion disclosure; duets/stitches off.")
    print("Manual TikTok posts are not covered by Upload-Post history; check profiles before submitting.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("preflight", "list", "publish", "status"), default="preflight")
    parser.add_argument("--queue", type=Path, default=Path("E:/Documents/pp/topspot-tiktok-teasers/publishing_queue.json"))
    parser.add_argument("--job", help="Exactly one slug|language")
    parser.add_argument("--at", help="Optional ISO-8601 scheduled time including offset")
    parser.add_argument("--confirm-not-posted", action="store_true")
    args = parser.parse_args()
    lock = Path(str(args.queue) + ".lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, str(os.getpid()).encode())
        queue = json.loads(args.queue.read_text(encoding="utf-8"))
        if args.action != "list":
            api = API()
            if args.action == "preflight":
                preflight(queue, api)
            elif args.action == "status":
                reconcile(queue, api)
            elif args.action == "publish":
                publish(queue, args.queue, api, args)
            save(args.queue, queue)
        show(queue)
        if args.action in {"preflight", "list"}:
            print("No videos uploaded or scheduled.")
    finally:
        os.close(descriptor)
        lock.unlink()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"STOPPED: {error}", file=sys.stderr)
        sys.exit(1)
