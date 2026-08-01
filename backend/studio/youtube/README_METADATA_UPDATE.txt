TOPSPOT40 — UPDATE THE 9 EXISTING YOUTUBE VIDEOS

FILES TO COPY INTO backend/studio/youtube/
  uploader.py
  update_metadata.py
  upload_manifest.local.json

The uploader.py file keeps all existing upload and thumbnail functions and adds
one metadata-only function. The update_metadata.py command cannot upload video
media or change visibility.

FROM THE REPOSITORY ROOT, PREVIEW FIRST:

python -m backend.studio.youtube.update_metadata \
  --manifest backend/studio/youtube/upload_manifest.local.json

Expected final lines:
  Success:  0
  Failure:  0
  Ready:    9

ONLY AFTER THE DRY RUN SHOWS READY: 9 AND FAILURE: 0, APPLY:

python -m backend.studio.youtube.update_metadata \
  --manifest backend/studio/youtube/upload_manifest.local.json \
  --client-secrets .cache-topspot/youtube/client_secret.json \
  --apply

Expected final lines:
  Success:  9
  Failure:  0

The command updates title, description, hidden tags, category, video language,
and audio language. It uses the existing video IDs in:
  backend/studio/work/youtube_upload_state.json

It does not re-upload videos, change thumbnails, or change public visibility.
