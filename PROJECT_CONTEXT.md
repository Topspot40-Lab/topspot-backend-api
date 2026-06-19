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
