"""Submit the saved TopSpot40 calendar or install its one-time Windows task.

Uses existing publisher safeguards and Windows Credential Manager.
Never creates approvals, changes dates, or resends uncertain uploads.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path("E:/Documents/pp/topspot-tiktok-teasers")
REPO = Path(__file__).resolve().parent
TASK = "TopSpot40-Submit-TikTok-Calendar-20261001"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate(plan, queue):
    from topspot_tiktok_batch import digest
    from topspot_tiktok_publisher import parse_time
    jobs = {j["id"]: j for j in queue["jobs"]}
    if len(jobs) != len(queue["jobs"]):
        raise RuntimeError("Duplicate queue IDs")
    used = set()
    pending = []
    for entry in plan["entries"]:
        if len(entry["jobs"]) != 3:
            raise RuntimeError("Each calendar day must contain three jobs")
        languages = set()
        at = parse_time(entry["planned_publish_at"])
        for item in entry["jobs"]:
            job = jobs[item["id"]]
            languages.add(job["language"])
            if job["slug"] != entry["slug"] or job["profile"] != item["profile"]:
                raise RuntimeError("Calendar account/story mismatch")
            key = (at.date(), job["profile"])
            if key in used:
                raise RuntimeError("Calendar exceeds one post per account/day")
            used.add(key)
            if job.get("approval") != "approved_by_Gary_in_chat":
                raise RuntimeError(f"Missing approval: {job['id']}")
            if job["sha256"] != item["sha256"] or digest(Path(job["video_file"])) != item["sha256"]:
                raise RuntimeError(f"Approved video changed: {job['id']}")
            if job.get("upload_request_id"):
                if (not job.get("provider_job_id") or
                        job.get("status") not in {"submitted", "provider_completed", "published"} or
                        not job.get("scheduled_at") or
                        parse_time(job["scheduled_at"]) != at):
                    raise RuntimeError(f"Existing submission needs reconciliation: {job['id']}")
                continue
            if at <= datetime.now(timezone.utc):
                raise RuntimeError(f"Scheduled time has passed: {job['id']}; replan, do not post immediately")
            pending.append(job["id"])
        if languages != {"en", "es", "pt-BR"}:
            raise RuntimeError("Calendar language set is incomplete")
    return pending


def run_submit():
    from topspot_tiktok_batch import write
    from topspot_tiktok_publisher import refresh_youtube
    queue_path = ROOT / "publishing_queue.json"
    plan_path = ROOT / "_shared/publishing_calendar.json"
    plan = load(plan_path)
    queue = load(queue_path)
    pending = validate(plan, queue)
    if not pending:
        plan["status"] = "submitted_to_upload_post"
        plan["submitted_at"] = plan.get("submitted_at") or datetime.now(timezone.utc).isoformat()
        write(plan_path, plan)
        print("All calendar jobs already submitted. Nothing resent.")
        return
    print(f"Checking YouTube before submitting {len(pending)} jobs...", flush=True)
    # If quota is exhausted, this fails before any Upload-Post mutation.
    refresh_youtube(queue)
    pending_set = set(pending)
    if any(not j.get("youtube_public") for j in queue["jobs"] if j["id"] in pending_set):
        raise RuntimeError("A calendar video is no longer public on YouTube; nothing submitted")
    for entry in plan["entries"]:
        at = entry["planned_publish_at"]
        for item in entry["jobs"]:
            # Reload after each subprocess: its request/job IDs are authoritative.
            latest = load(queue_path)
            validate(plan, latest)
            job = next(j for j in latest["jobs"] if j["id"] == item["id"])
            if job.get("upload_request_id"):
                print("SKIP already submitted:", job["id"], flush=True)
                continue
            print("SCHEDULE:", job["id"], at, flush=True)
            result = subprocess.run([
                sys.executable, str(REPO / "topspot_tiktok_publisher.py"),
                "publish", "--queue", str(queue_path), "--job", job["id"],
                "--at", at, "--confirm-not-posted",
            ], capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(result.stdout, end="", flush=True)
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr, flush=True)
            if result.returncode:
                raise RuntimeError(f"Publisher stopped at {job['id']}; do not blindly resend")
            current = load(queue_path)
            validate(plan, current)
    final = load(queue_path)
    if validate(plan, final):
        raise RuntimeError("Some calendar jobs remain unsubmitted")
    plan["status"] = "submitted_to_upload_post"
    plan["submitted_at"] = datetime.now(timezone.utc).isoformat()
    write(plan_path, plan)
    print("CALENDAR SUBMITTED. These are scheduled jobs, not confirmed live posts.")


def submit():
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "_calendar_submit.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    logs = ROOT / "_shared/logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / ("calendar_submit_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".log")
    try:
        print("Writing submission log:", path)
        with path.open("w", encoding="utf-8", buffering=1) as stream:
            with redirect_stdout(stream), redirect_stderr(stream):
                try:
                    run_submit()
                except BaseException as error:
                    print("STOPPED:", error, flush=True)
                    raise
        print("Finished. Review:", path)
    finally:
        os.close(descriptor)
        lock.unlink()


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def install_task():
    if os.name != "nt":
        raise RuntimeError("Task installation requires Gary's Windows computer")
    when = "2026-10-01T08:00:00-05:00"
    if datetime.fromisoformat(when) <= datetime.now(timezone.utc):
        raise RuntimeError("The planned task time has passed; run submit manually before the first post time")
    # Verify saved credential exists, without printing it or making a request.
    from keyring.backends.Windows import WinVaultKeyring
    if not WinVaultKeyring().get_password("TopSpot40.UploadPost", "factory"):
        raise RuntimeError("Saved Upload-Post credential is missing")
    validate(load(ROOT / "_shared/publishing_calendar.json"), load(ROOT / "publishing_queue.json"))
    arguments = '"' + str(Path(__file__).resolve()) + '" submit'
    script = f"""
$ErrorActionPreference = 'Stop'
$when = [DateTimeOffset]::Parse({ps_quote(when)}).LocalDateTime
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute {ps_quote(sys.executable)} -Argument {ps_quote(arguments)} -WorkingDirectory {ps_quote(REPO)}
$trigger = New-ScheduledTaskTrigger -Once -At $when
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName {ps_quote(TASK)} -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Get-ScheduledTaskInfo -TaskName {ps_quote(TASK)} | Select-Object NextRunTime, LastTaskResult | Format-List
"""
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], check=True)
    print("ONE-TIME TASK INSTALLED: October 1, 8:00 AM Chicago.")
    print("Keep the computer on, awake, connected, and signed in for submission.")
    print("After provider acceptance, Upload-Post handles the daily publishing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install-task", "submit"))
    args = parser.parse_args()
    try:
        if args.action == "install-task":
            install_task()
        else:
            submit()
    except Exception as error:
        print("STOPPED:", error, file=sys.stderr)
        sys.exit(1)
