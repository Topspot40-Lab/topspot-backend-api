# PROJECT_CONTEXT.md - TopSpot40 Backend

# Project Overview

TopSpot40 is a music discovery and playback platform centered around curated rankings of songs by genre and decade and collections and artist spotlight. This repository contains the backend API responsible for authentication, authorization, business logic, subscriptions, data access, playback, intro/detail/artist mp3, and integrations with external services.

The backend is the source of truth for application logic.

---

# Technologies

* FastAPI
* Python
* SQLModel
* Supabase (database and storage)
* Stripe (subscriptions and billing)
* Spotify Web API
* OAuth 2.0 Authorization Code Flow
* Pytest

---

# Architectural Principles

* Business logic belongs in the backend.
* Frontend clients should remain thin whenever practical.
* Route design should follow REST principles.
* Resource-oriented APIs are preferred over action-oriented APIs.
* Code should be easy to evolve, debug, and test.
* Favor explicitness over cleverness.

---

# Authentication and Authorization

IMPORTANT:

Spotify OAuth is handled entirely by the backend.

The frontend does NOT implement OAuth logic.

Current production Spotify/session flow:

* `backend/isaiah/isaiah_router.py` initiates Spotify OAuth, handles callbacks, creates or looks up TopSpot40 users, stores Spotify tokens in Supabase, and establishes the backend session cookie.
* `backend/isaiah/isaiah_spotify.py` exchanges and refreshes Spotify tokens and reads/writes user token records in Supabase.
* `backend/isaiah/jwt_session.py` creates and decodes the backend session JWT used to identify the authenticated TopSpot40 user.

Backend responsibilities include:

* Initiating Spotify OAuth flow.
* Handling OAuth callbacks.
* Exchanging authorization codes for tokens.
* Refreshing Spotify access tokens.
* User creation and lookup.
* Session establishment.
* Authorization checks.
* Admin authentication.

Any modifications affecting authentication must preserve existing login behavior.

Known authentication context:

* Spotify access and refresh tokens are owned by a TopSpot40 user and are stored in Supabase.
* Playback code must use the authenticated user's Spotify token. It must not use a shared Spotipy client, shared OAuth manager, or shared token cache for playback ownership.
* Legacy Spotify auth paths still exist in `backend/routers/spotify_auth.py` and `backend/services/spotify/spotify_auth_user.py`. These include cache/auth-manager code originally used for local or debug flows. They must not be assumed to be the production playback authentication architecture unless explicitly revalidated.
* Token refresh currently reads an expired Supabase token record, refreshes it with Spotify, then updates the Supabase row. The codebase does not currently document or visibly enforce a per-user refresh lock or compare-and-swap style update, so concurrent refresh behavior should be treated as a known concurrency consideration.

---

# Playback Architecture and Migration State

TopSpot40 playback is in an active migration from a single-user/shared-state model toward production multi-user playback isolation.

Current implementation:

* Playback routes live primarily in:
  * `backend/routers/playback_control.py`
  * `backend/routers/playback_status.py`
  * `backend/routers/decade_genre_player.py`
  * `backend/routers/collections_player.py`
  * `backend/routers/single_track_player.py`
  * `backend/routers/artist_spotlight.py`
* Playback sequences and helpers live primarily in:
  * `backend/services/decade_genre_sequence.py`
  * `backend/services/collection_sequence.py`
  * `backend/services/collections_radio_sequence.py`
  * `backend/services/all_radio_sequence.py`
  * `backend/services/radio_runtime.py`
  * `backend/services/playback_helpers.py`
  * `backend/services/radio/narration.py`
  * `backend/services/radio/heartbeat.py`
* `backend/state/playback_runtime.py` defines a process-local `runtime_by_user` mapping and task-to-user binding helpers.
* `PlaybackRuntime` contains per-user runtime fields for status, flags, current task, playback events, locks, and Spotify client references.
* `backend/state/playback_state.py` currently stores `PlaybackStatus` objects in a process-local `statuses` dictionary keyed by `user_id`.
* `backend/state/playback_flags.py` currently has both a process-local `flags_by_user` dictionary and a remaining module-level `flags = PlaybackFlags()` instance.
* `backend/state/narration.py` currently stores narration and track completion events in process-local dictionaries keyed by `user_id`.
* `backend/state/skip.py` exposes `skip_event` through the runtime proxy model.

Required invariants:

* Playback state must be scoped to the authenticated TopSpot40 user.
* One user's request must not be able to start, pause, resume, stop, skip, advance, unblock, or otherwise mutate another user's playback.
* Playback routes must derive user ownership from the authenticated backend session cookie/JWT. They must not trust `user_id` supplied by query parameters, request bodies, or frontend-controlled state when selecting runtime state, Spotify tokens, Spotify devices, or playback events.
* `status`, `flags`, `current_task`, `sequence_lock`, `track_done_event`, `narration_done_event`, `skip_event`, and Spotify client/token access must resolve to the authenticated user's playback runtime.
* Track and narration completion events must be routed to the correct user-specific event object.
* `start_new_sequence` and sequence cancellation must only affect the authenticated user's active playback task.
* Any `asyncio.create_task(...)` that directly or indirectly accesses playback state, playback events, Spotify playback, or runtime helpers must be associated with the owning user before that child task accesses runtime-backed state.
* Spotify playback operations must use the authenticated user's Supabase-backed Spotify token record.

Known incomplete migration areas:

* Some playback code still imports or mutates shared/global state, especially the remaining module-level `flags` instance.
* Some playback status/event routes currently accept `user_id` as an API parameter instead of deriving it from the authenticated session.
* Some background tasks created inside playback helpers access runtime-backed state or playback events without a clearly visible task ownership binding at the task creation site.
* Some active playback code still imports Spotify helpers from the legacy `spotify_auth_user.py` module, even though that helper currently delegates token lookup to Supabase.
* Legacy Spotify auth routes are still registered in `backend/main.py`.
* Some playback code appears to mix older call signatures with newer user-scoped helper signatures. Treat this subsystem as mid-migration rather than fully isolated.

Known limitations:

* Playback runtime state is process memory. `runtime_by_user`, `_task_user`, `statuses`, `flags_by_user`, narration event dictionaries, track event dictionaries, and `asyncio.Event` / `asyncio.Lock` objects are not shared across backend processes.
* Active playback tasks are in-process only. They are not durable across restarts and cannot move between backend instances.
* If the backend runs multiple workers or multiple instances without sticky routing or a shared coordination layer, status polling, event callbacks, skip/pause/stop commands, and active sequence loops may land on different processes.
* The current process-memory model is acceptable only as an interim single-instance migration step. It is not, by itself, horizontally scalable.

Future architectural considerations:

* Horizontal scaling will require a deliberate strategy for runtime ownership, event delivery, active sequence coordination, and status visibility across backend instances.
* Token refresh concurrency should be made explicit if multiple simultaneous requests can refresh the same user's Spotify token.
* Legacy Spotify auth/cache routes should be clearly separated from, or removed from, production playback authentication once compatibility requirements are known.

---

# Billing

Stripe is used for subscription management.

Requirements:

* Paying users receive access according to subscription status.
* Testers may bypass Stripe when explicitly authorized.
* Stripe webhook events synchronize subscription state into Supabase.
* Subscription synchronization must remain idempotent.

Billing-related changes require regression tests.

---

# Database Philosophy

Supabase serves as the primary data store.

Changes to database schemas must:

* Preserve data integrity.
* Include migration considerations.
* Consider backwards compatibility.
* Include tests for affected functionality.

---

# Quality Standards

Software quality means:

* Correctness.
* Security.
* Reliability.
* Maintainability.
* Evolvability.
* Performance.
* Fitness for use.

The goal is not merely to satisfy specifications, but to satisfy user needs.

---

# Testing Philosophy

Use Test-Driven Development whenever practical.

Testing hierarchy:

1. Unit Tests
2. Functional Tests
3. Integration Tests
4. System / Acceptance Tests

Avoid redundant testing between levels.

Regression tests should prevent previously working functionality from breaking.

Coverage targets are indicators, not goals.

Meaningful tests are preferred over artificial coverage increases.

---

# REST Guidelines

Routes should represent resources.

Preferred examples:

GET /tracks/{id}

POST /subscriptions

PATCH /users/{id}

DELETE /testers/{id}

Avoid action-oriented routes whenever reasonable.

---

# Code Review Checklist

Before approving changes ask:

* Did we build the thing right?
* Did we build the right thing?
* Are edge cases covered?
* Is authentication still secure?
* Can this change allow one user to affect another user's playback?
* Does playback state resolve from the authenticated user rather than client-supplied user identity?
* Are background playback tasks bound to the correct user before touching runtime state?
* Does Spotify playback use the authenticated user's token ownership?
* Could this change impact Stripe synchronization?
* Could this change affect existing users?
* Are tests present and meaningful?
* Is the implementation easy to understand?

---

# AI Agent Instructions

When working in this repository:

* Understand the affected subsystem before editing code.
* Do not rewrite large portions of the application without justification.
* Prefer minimal, targeted changes.
* Preserve existing functionality unless explicitly instructed otherwise.
* Explain architectural tradeoffs before major refactors.
* Generate tests alongside production code whenever practical.
* If uncertain about intent, ask for clarification instead of guessing.

The backend prioritizes correctness over speed of implementation.
