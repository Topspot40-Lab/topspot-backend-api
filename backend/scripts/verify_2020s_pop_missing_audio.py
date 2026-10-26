"""Confirm missing reused narration by downloading the specific objects (read-only).

    python -m backend.scripts.verify_2020s_pop_missing_audio \
      --preflight 2020s-pop-preflight.json --output 2020s-pop-audio-check.json
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.preflight.read_text(encoding="utf-8"))
    if report.get("problems") or report.get("possible_name_collisions") or report.get("reused_audio_checked") != 30:
        raise ValueError("Unexpected preflight report; resolve database conflicts first")
    missing = report["missing_reused_audio"]
    if len(missing) > 30:
        raise ValueError("Unexpected number of missing files")
    from backend.services.supabase_client import supabase
    confirmed = []
    found = []
    errors = []
    for item in missing:
        bucket, key = item["bucket"], item["key"]
        if bucket not in ("audio-en", "audio-es", "audio-ptbr") or not key.endswith(".mp3") or not key.startswith(("detail/", "artist/")) or "/" in key.split("/", 1)[1]:
            raise ValueError(f"Unexpected object location: {bucket}/{key}")
        try:
            data = supabase.storage.from_(bucket).download(key)
        except Exception as exc:
            # A permissions or network failure must not be mistaken for a missing object.
            code = getattr(exc, "status", None) or getattr(exc, "status_code", None)
            message = str(exc)
            if str(code) == "404" or "not_found" in message.lower() or "not found" in message.lower():
                confirmed.append(item)
                print(f"MISSING {bucket}/{key}", flush=True)
            else:
                errors.append({**item, "error": message[:300]})
                print(f"ERROR {bucket}/{key}: {message[:160]}", flush=True)
        else:
            if len(data) > 1000 and (data.startswith(b"ID3") or data[:1] == b"\xff"):
                found.append(item)
                print(f"FOUND   {bucket}/{key}", flush=True)
            else:
                confirmed.append(item)
                print(f"EMPTY/INVALID {bucket}/{key}", flush=True)
    result = {"preflight_missing": len(missing), "confirmed_missing": confirmed,
              "found_by_download": found, "download_errors": errors}
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Confirmed missing: {len(confirmed)}; found by download: {len(found)}; errors: {len(errors)}")
    print(f"Saved {args.output}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
