# TopSpot40 Backend Project Context

This file summarizes the currently verified backend implementation. Current code, configuration, tests, Git state, and command output remain the source of truth.

## Purpose and Responsibilities

`topspot-backend-api` is the FastAPI backend for TopSpot40.

Verified responsibilities include:

- Catalog APIs for TopSpot40 music and content data.
- Active legacy Spotify OAuth, backend session, user-token, and playback-control routes that remain present in code.
- Newer approved Spotify public-link companion material that sends listeners to public Spotify song pages without describing OAuth-controlled playback as the current product direction.
- Stripe checkout, subscription status, and webhook handling.
- Supabase/Postgres-backed data access.
- Feedback intake.
- Studio and operational tooling for content generation, rendering, imports, and storage workflows.

Evidence includes `backend/main.py::app`, routers under `backend/routers/`, authentication and billing code in `backend/isaiah/isaiah_router.py`, models in `backend/models/dbmodels.py`, and Studio tooling under `backend/studio/`.

## Technology and Configuration

Dependencies are declared in `requirements.txt`.

Verified dependency areas include:

- FastAPI, Starlette, and Uvicorn.
- SQLModel, SQLAlchemy, and psycopg2.
- Supabase client, storage, and realtime packages.
- Spotipy, httpx, and requests.
- Stripe.
- PyJWT.
- python-dotenv.
- pytest, pytest-asyncio, and pytest-mock.
- Pillow.
- Script and Studio support for ffmpeg/ffprobe-driven media workflows and xAI-compatible HTTP helpers.

Some scripts import `openai.OpenAI`, but `openai` is not declared in `requirements.txt`, so script dependencies are not fully represented by the current dependency file.

Runtime configuration reads environment variables through:

- `backend/config/__init__.py`
- `backend/database.py`
- `backend/isaiah/isaiah_helper.py`
- `backend/services/supabase_client.py`

Database configuration is in `backend/database.py`. `backend/database.py::engine` reads `DATABASE_URL`, `POSTGRES_URL`, or `SUPABASE_DB_URL`, creates a SQLModel engine with `NullPool`, `pool_pre_ping`, and `sslmode=require`, and exposes `backend/database.py::get_db` and `backend/database.py::get_db_session`.

## Application Entrypoint and Active Router Registration

The FastAPI application entrypoint is `backend/main.py::app`.

Active routers are registered in `backend/main.py`:

- `backend.routers.health.router`
- `backend.routers.catalog.router`
- `backend.routers.artist_spotlight.router`
- `backend.routers.playback_status.router`
- `backend.routers.decade_genre_player.router`
- `backend.routers.collections_player.router`
- `backend.routers.decade_genre_pause.router`
- `backend.routers.playback_control.router`
- `backend.routers.feedback.feedback_router` under `/api`
- `backend.isaiah.isaiah_router.spotify_user_auth_router` under `/api/auth`
- `backend.isaiah.isaiah_router.stripe_router` under `/api`
- `backend.routers.supabase_collections.router`
- `backend.routers.music_docuseries.router`
- `backend.routers.admin.router`

## Major Backend Modules

`backend/routers/` contains the active HTTP surface for health, catalog, playback, collections, artist spotlight, feedback, admin, and music docuseries routes.

`backend/isaiah/` contains Spotify OAuth, JWT cookie session behavior, Spotify token persistence, Stripe subscription routes, and Stripe webhook handling.

`backend/services/` contains playback sequencing, Spotify playback/client creation, Supabase helpers, audio URL/storage helpers, xAI/TTS helpers, and radio runtime support.

`backend/state/` contains in-process playback runtime state, per-user flags, status, skip/narration/track events, locks, and task ownership helpers.

`backend/models/` contains SQLModel entities for catalog, rankings, locales, collections, artist stories, music docuseries, music discovery, feedback, and related data.

`backend/scripts/` and `backend/studio/` contain operational content generation, imports, TTS, storage upload/delete helpers, Studio production sessions, audio/video rendering, and station workflows.

## Authentication and Session Flow

Spotify login begins at `/api/auth/spotify/login` via `backend/isaiah/isaiah_router.py::spotify_login`.

Spotify callback is `/api/auth/spotify/callback` via `backend/isaiah/isaiah_router.py::spotify_callback`.

The callback flow:

1. Exchanges the Spotify OAuth code.
2. Fetches the Spotify profile.
3. The active legacy callback implementation rejects Spotify accounts whose returned product value is not "premium".
4. Creates or updates `topspot_users`.
5. Upserts `spotify_tokens`.
6. Creates a JWT with `backend/isaiah/jwt_session.py::create_jwt_token`.
7. Sets an HTTP-only cookie named `access_token`.

JWT decoding is handled by `backend/isaiah/jwt_session.py::decode_jwt_token`.

Cookie and frontend/backend URL helpers are in `backend/isaiah/isaiah_helper.py`. The verified current cookie configuration includes domain `.topspot40.com` and secure cookies.

Generated Spotify public-link companion pages describe a newer approved model where TopSpot40 links listeners to Spotify song pages and does not require Spotify authorization or Spotify Premium because listeners use Spotify directly. That companion model should not be described as OAuth-controlled backend playback.

## Spotify Integration and Token Ownership

Spotify token exchange, profile lookup, token refresh, and valid-token lookup are in `backend/isaiah/isaiah_spotify.py`.

The active token ownership path is user-scoped:

1. The backend session cookie is decoded.
2. The TopSpot user id is extracted from the JWT payload.
3. `backend/isaiah/isaiah_spotify.py::get_valid_access_token(user_id)` reads or writes `spotify_tokens` for that user.
4. `backend/services/spotify/spotify_auth_user.py::get_spotify_user_client(user_id)` returns a Spotipy client for that user token.
5. `backend/services/spotify/playback.py::play_spotify_track` performs playback operations with an authenticated `user_id`.

Active `/api/auth/spotify/token` and `/api/auth/spotify/sdk-token` endpoints decode the backend JWT cookie and pass `payload["user_id"]` to `get_valid_access_token`.

This active token ownership path is legacy/current-code behavior, not evidence that OAuth-controlled playback is the intended current product direction.

Generated catalog/link-out companion material treats Spotify as an external public destination. It describes TopSpot40 as linking to public Spotify song pages without hosting music, requiring Spotify authorization, storing Spotify access tokens, or controlling playback devices.

## Stripe and Subscription Flow

Stripe routes are defined in `backend/isaiah/isaiah_router.py::stripe_router` and registered under `/api`.

Active routes include:

- `POST /api/create-checkout-session`
- `GET /api/verify-subscription`
- `GET /api/subscription-status`
- `POST /api/webhooks/stripe`

`backend/isaiah/isaiah_router.py::create_checkout_session` decodes the JWT cookie, uses the authenticated `user_id` as Stripe `client_reference_id`, sets `metadata.topspot_user_id`, and returns `{"url": session.url}`.

`backend/isaiah/isaiah_router.py::verify_subscription` decodes the JWT cookie, allows `topspot_users.is_tester`, retrieves Stripe checkout/subscription details, and returns JSON subscription status fields.

`backend/isaiah/isaiah_router.py::get_subscription_status` decodes the JWT cookie, checks tester bypass, and looks for active rows in `subscriptions`.

`backend/isaiah/isaiah_router.py::stripe_webhook` verifies the Stripe signature, inserts event id/type into `stripe_webhook_events` for duplicate detection, and syncs subscription records through `sync_subscription_to_supabase`.

## Database and Supabase Integration

SQLModel models live in:

- `backend/models/dbmodels.py`
- `backend/models/collection_models.py`

Major modeled entities include artists, tracks, decades, genres, decade/genre rankings, track locales, artist locales, artist stories, collections, collection rankings, music docuseries, music discovery, and collection stories.

Service-role Supabase clients exist in:

- `backend/isaiah/isaiah_router.py::supabase`
- `backend/isaiah/isaiah_spotify.py::supabase`
- `backend/services/supabase_client.py::supabase`

Storage helpers live in `backend/services/supabase_storage.py`.

Audio URL resolution is handled by `backend/services/audio_urls.py` and is controlled by `AUDIO_MODE`.

Verified directly referenced Supabase tables include:

- `topspot_users`
- `spotify_tokens`
- `subscriptions`
- `stripe_webhook_events`
- `feedback`

## Catalog and Content APIs

Catalog routes are in `backend/routers/catalog.py` under `/api/catalog`.

Verified backend catalog contracts include:

- `GET /api/catalog/summary`
- `GET /api/catalog/get-json-catalog`
- `GET /api/catalog/grouped`

Decade/genre sequence and playback routes are in `backend/routers/decade_genre_player.py` under `/supabase/decade-genre`.

Collection sequence and playback routes are split between:

- `backend/routers/supabase_collections.py`
- `backend/routers/collections_player.py`

Artist Spotlight routes are in `backend/routers/artist_spotlight.py`.

Music docuseries routes are in `backend/routers/music_docuseries.py`.

## Playback Architecture and User Ownership

Playback runtime ownership is centered on `backend/state/playback_runtime.py`.

Protected playback routes use `backend/state/playback_runtime.py::bind_request_user`, which decodes the `access_token` cookie and binds the current asyncio task to the authenticated user id.

`backend/state/playback_runtime.py::get_runtime_for_user(user_id)` creates per-user `PlaybackRuntime` objects containing status, flags, current task, events, and locks.

`backend/routers/playback_control.py::start_new_sequence` cancels only the current user runtime task, starts `start_playback_session(user_id)`, creates a background task, and binds that task to the user id.

Public playback status is returned by `backend/routers/playback_status.py::get_status`. The response uses camelCase playback fields such as `isPlaying`, `isPaused`, `playbackSessionId`, `elapsedMs`, `durationMs`, and `context`.

Verified ownership model:

- Protected playback routes bind request ownership from the authenticated backend session cookie.
- Per-user runtime state is keyed by user id through `runtime_by_user[user_id]`.
- Spotify playback calls include authenticated `user_id`.
- Inspected playback status and event endpoints use current_user_id() and user-keyed events or status. Complete end-to-end isolation across every playback path has not been proven.

## Studio and Operational Tooling

`backend/studio/` contains offline Studio production workflows.

Verified Studio areas include:

- `backend/studio/studio_config.py`
- `backend/studio/production.py::Production`
- `backend/studio/factory/production_session.py::ProductionSession`
- `backend/studio/audio/build_youtube_audio.py`
- `backend/studio/audio/build_language_masters.py`
- `backend/studio/render/build_story_video.py`
- `backend/studio/render/build_image_sequence.py`
- `backend/studio/visuals/generate_images.py`
- `backend/studio/visuals/image_quality.py`
- `backend/studio/catalog_completed_youtube_assets.py`
- `backend/models/studio_models.py::StudioProductionAsset`
- `backend/studio/stations/*`

Current Studio tooling includes YouTube/video asset cataloging and current-asset lookup through `StudioProductionAsset`, image QA/regeneration, approved historical-image handling, opening-card/image-sequence/story-video rendering, and language-master/YouTube audio assembly. Some tooling invokes ffmpeg/ffprobe, xAI image APIs, Supabase storage, or database writes depending on command options.

The Studio artist-photo workflow builds Wikimedia/PICRYL-style review pages, ranks and filters candidate images, generates copyable approval commands, downloads approved Wikimedia candidates, uploads approved artist photos to Supabase Storage bucket `historical-images`, writes approved metadata under `backend/studio/assets/historical/artists/{letter}/{artist_slug}/metadata`, and can assign approved artist photos to safe storyboard shots for artist productions.

Approved Al Jarreau artist-photo metadata currently includes eight records under `backend/studio/assets/historical/artists/a/al_jarreau/metadata/`, from `001-al-jarreau-molde.json` through `008-jarreaualduesseldorf1981.json`. These records identify `artist_id` 945, `artist_slug` `al_jarreau`, provider `wikimedia_commons`, `approved: true`, approved image filenames, and Supabase Storage keys under `historical-images/artists/a/al_jarreau/photos/`. All eight referenced Supabase Storage objects were previously verified to exist in a read-only point-in-time check; this does not imply permanent availability.

`backend/scripts/` contains operational/content-generation scripts for imports, generated text, generated TTS, collection/docuseries/music-discovery data, cleanup workflows, database writes, and storage operations.

Studio and script files may create local files, call external APIs, invoke ffmpeg, write Supabase/Postgres/storage data, or incur cost.

## Current Testing and Quality-Tooling Status

Current pytest files in `backend/tests/` are:

- `test_artist_photo_workflow.py`
- `test_artist_spotlight_youtube.py`
- `test_auth_and_stripe.py`
- `test_isaiah_spotify_auth.py`
- `test_isaiah_spotify_router.py`

Pytest config exists at `backend/pytest.ini` with `pythonpath = .` and `asyncio_mode = strict`.

Artist-photo workflow tests cover storage-key layout, filename normalization, next photo numbering, artist matching, safe-shot filtering, approval command generation, and production-directory photo lookup.

Artist Spotlight YouTube tests cover `artist_story` response fields and newest-version ordering.

The test suite was not run or collected during the read-only audit.

No verified lint, format, type-check, coverage, CI, build, or canonical local startup command was found.

Do not describe backend tests as reliable, complete, collecting, or passing unless verified during the current task.

## Runtime and Deployment Facts That Are Actually Verified

`backend/main.py::root` returns HTML identifying the backend and saying `Environment: Render`.

CORS in `backend/main.py` allows local Vite origins, `https://topspot40.com`, `https://www.topspot40.com`, `https://topspot40.netlify.app`, `https://sparkling-croissant-23bbac.netlify.app`, and `https://resplendent-gaufre-032b1a.netlify.app`, with credentials enabled.

Production helper URLs in `backend/isaiah/isaiah_helper.py` currently point Spotify callback traffic to `https://api.topspot40.com/api/auth/spotify/callback` and frontend redirects to `https://topspot40.com`.

`requirements.txt` includes `uvicorn`.

No canonical backend startup command or deployment config was verified.

## Cross-Repository Contracts

The audit identified the following backend routes as current or expected frontend integration contracts:

- Spotify OAuth: `/api/auth/spotify/login`
- Current user/auth info: `/api/auth/me`
- Subscription status: `/api/subscription-status`
- Stripe checkout: `/api/create-checkout-session`
- Stripe verification: `/api/verify-subscription`
- Catalog: `/api/catalog/grouped`, `/api/catalog/summary`
- Playback status/control: `/playback/status`, `/playback/devices`, `/playback/client-diagnostic`, `/playback/transfer/{device_id}`, `/playback/narration-finished`, `/playback/track-finished`, `/playback/play-spotify`, `/playback/play-track`, `/playback/flags-status`, `/playback/start`, `/playback/pause`, `/playback/resume`, `/playback/stop`, `/playback/skip`, `/playback/warmup`, `/playback/reset`
- Supabase-backed sequences: `/supabase/decade-genre/*`, `/supabase/collections/*`
- Artist spotlight: `/artist-spotlight/*`
- Music docuseries: `/music-docuseries/*`

Frontend response-shape compatibility was not exhaustively audited.

## Legacy or Inactive Areas

`backend/routers/spotify_auth.py` is unregistered in `backend/main.py` and includes a file-cache OAuth path through `.cache-topspot/spotify_token.cache`.

`backend/routers/single_track_player.py` is unregistered in `backend/main.py`.

`backend/isaiah/isaiah_router.py::spotify_refresh` has its decorator commented out.

`backend/routers/playback_control.py::flags_status` is an active legacy/debug-looking route.

## Known Inconsistencies Requiring Resolution

`backend/main.py` includes duplicate active router registrations for `stripe_router` and `feedback_router`.

Playback status has split storage. `PlaybackRuntime.status` is separate from `backend/state/playback_state.py::statuses[user_id]`. Functions such as `update_phase`, `mark_playing`, `begin_track`, and `/playback/status` use `playback_state.get_status(user_id)`, while some route/service code reads `current_runtime().status`.

`backend/routers/artist_spotlight.py::play_artist_radio` creates and binds a background task but does not store it in `current_runtime().current_task`.

Existing backend tests appear stale against active route prefixes/current behavior. Examples from the audit include tests calling `/spotify/login`, `/spotify/token`, and `/create-checkout-session`, while active registrations expose `/api/auth/spotify/login`, `/api/auth/spotify/token`, and `/api/create-checkout-session`. A subscription verification test expects a redirect, while current `verify_subscription` returns JSON.

Backend and frontend production frontend URLs differ in verified code. Backend helper code uses `https://topspot40.com`, while frontend `src/lib/config.ts::FRONTEND_URL` uses `https://resplendent-gaufre-032b1a.netlify.app`.

## Known Limitations and Unresolved Facts

No live DB, Stripe, Spotify, Supabase, xAI, ElevenLabs, ffmpeg, service runtime, or external-service behavior was exercised during the read-only audit.

The live production database schema was not verified. SQLModel models are evidence of application expectations, not proof of live schema.

No backend tests were run or collected during the read-only audit.

No deployment platform configuration file or canonical local startup command was verified.

Admin tester route `backend/routers/admin.py::set_tester` uses an `ADMIN_SECRET` header check and service-role Supabase writes; no additional authorization model was verified in inspected code.

Spotify is the currently implemented playback integration. This document does not establish Spotify as TopSpot40's approved long-term playback provider or confirm that the current integration can support production-scale usage.
