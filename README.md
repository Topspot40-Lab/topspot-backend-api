# Docuseries hook title update

Apply to the uploaded topspot-backend-studio source (branch gary/rebuild-corrected-docuseries).

The hook stays 1920x1080. It shows the approved localized title above the complete source picture, blurred fill beside the image, a translated MUSIC DOCUMENTARY label, and TopSpot40.com underneath. The frame stays visible throughout hook narration and its existing pause. Opening cards, audio, chapter timing, intro, main story and outro are unchanged. The TikTok spoken CTA is not inserted into the full documentary.

Existing completed legacy deliveries do not rebuild merely because of this layout update. Unfinished deliveries use the new frame. Existing source changes still trigger the factory's normal rebuild behavior; completed legacy videos retain their legacy artwork in that case. New styled deliveries resume without rerendering when inputs match. Corrupted/interrupted deliveries that the execution system marks pending receive the new frame.

Titles use the factory's existing multilingual YouTube title map. To override or add an upcoming topic, add this to its production manifest (do not change source identifiers):

```json
"hook_titles": {
  "en": "George Martin: The Fifth Beatle",
  "es": "George Martin: El quinto Beatle",
  "pt-BR": "George Martin: O quinto Beatle"
}
```

Missing Spanish or Portuguese titles stop that language's render with a clear message. Arial Bold on Windows or DejaVu Sans is required; Pillow is already used by the factory.

## Apply

Extract this ZIP to E:/Documents/pp/docuseries-hook-update. In Git Bash:

```bash
cd /e/Documents/pp/topspot-backend-studio
git status --short
git apply --check --ignore-whitespace /e/Documents/pp/docuseries-hook-update/docuseries-hook-title.patch
git apply --ignore-whitespace /e/Documents/pp/docuseries-hook-update/docuseries-hook-title.patch
python -m unittest discover -s tests -p test_hook_title_frame.py
git diff --stat
```

If the check fails, stop and share its output. Do not overwrite locally changed files with the included reference source. Run the usual documentary factory command for one unfinished topic, then inspect the hook in all three languages before scaling up. Do not reset completed execution records to force this update onto old videos.

## Validation

Seven standalone checks passed: all three languages and image dimensions/source preservation, missing-translation/override behavior, long-title fitting, completed legacy protection, pending adoption, styled resume, and normal input-change rebuilds. Python compilation and patch application against a fresh copy of the uploaded ZIP passed. These tests execute the actual station control flow with fake execution/session objects, avoiding database and paid services. No full documentary render was run because local production assets and services were not included. The source files are included for review, alongside the patch and tests.
