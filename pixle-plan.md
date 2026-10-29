# Pixle — Project Plan

## 1. Overview

**Pixle** is a daily photo-mosaic guessing game.

Players identify a famous person from a photo rendered as a mosaic of images of other famous people. The mosaic becomes more detailed across difficulty levels. The earlier the player guesses correctly, the better their score.

**Core principles**
- One shared daily puzzle for all players.
- Simple, fast, browser-based gameplay.
- Globally recognizable contemporary personalities.
- Minimal friction: no account required.

## 2. Gameplay

1. Display the daily target as a coarse photo mosaic.
2. Let the player guess the person's identity.
3. Reveal progressively finer mosaic levels after incorrect guesses.
4. Award a score based on how early the player guesses correctly.
5. Show the result and allow sharing.

**Initial scope**
- One puzzle per day.
- Approximately 100 curated personalities.
- Multiple mosaic resolutions.
- Guess input with suggestions.
- Results and basic statistics.
- Responsive desktop and mobile UI.

## 3. Technology Stack

| Component | Technology |
|---|---|
| Frontend | React + TypeScript |
| Build tool | Vite |
| Backend | Python + FastAPI |
| Database | PostgreSQL |
| Image processing | Python + Pillow + NumPy |
| Reverse proxy / HTTPS | Caddy |
| Deployment | Docker Compose on a VPS |

## 4. Architecture

```text
Browser
   |
   v
Caddy (HTTPS)
   ├── /       -> React static files
   └── /api/*  -> FastAPI
                     |
                     v
                 PostgreSQL

Static mosaic images and assets are served directly by Caddy.
Image processing runs offline during puzzle preparation.
```

**Responsibilities**

- **Frontend:** Mosaic display, guesses, difficulty levels, score presentation and local progress.
- **Backend:** Daily puzzle selection, answer validation, result submission and statistics.
- **PostgreSQL:** Puzzle metadata, anonymous player identifiers and game results.
- **Image pipeline:** Download, normalize and process source images; generate mosaic assets before publication.

## 5. Image Pipeline

- Curate approximately 100 globally recognizable contemporary people.
- Obtain suitable photographs and verify their usage licenses.
- Store square, normalized source images in `/people/images`.
- Maintain attribution, source URL and license metadata for each image.
- Generate mosaic tiles from other people, excluding the target image.
- Match tiles to target-image regions based on average color.
- Precompute mosaic assets for each daily puzzle.

## 6. Data & Privacy

- No registration required.
- Use a random pseudonymous player ID if cross-session statistics are needed.
- Store only necessary game results.
- Collect aggregate statistics such as completion rate, attempts and return frequency.
- Do not use IP addresses as player identifiers.
- Validate submissions and prevent duplicate results where appropriate.

## 7. MVP Priorities

1. Build the image-processing pipeline.
2. Create a curated dataset of 30–50 people.
3. Implement the mosaic gameplay and responsive UI.
4. Add daily puzzle selection and answer validation.
5. Persist results and calculate basic statistics.
6. Deploy to a VPS with HTTPS.
7. Test with real users before expanding the dataset.

## 8. Out of Scope Initially

- User accounts and authentication.
- Multiplayer or real-time features.
- Leaderboards and competitive rankings.
- Multiple game modes or categories.
- Microservices, message queues and complex infrastructure.

## 9. Key Risks

- **Image licensing:** Verify permissions and attribution requirements before publication.
- **Puzzle quality:** Ensure targets are recognizable and mosaic difficulty progresses meaningfully.
- **Answer leakage:** Keep the target identity out of publicly served assets when practical.
- **Engagement:** Test whether players return for subsequent daily puzzles.
- **Abuse:** Treat client-submitted results as untrusted input.

## Implementation Plan

Deliver the MVP in the sequence below. Keep the image-curation workflow offline and
publish only reviewed puzzle assets and the data required by each application
component.

### [x] 0. Complete and review the portrait dataset

- [x] Resolve the six people without downloaded portraits; keep any unavailable or
  unsuitable source explicitly recorded rather than substituting an unverified image.
- [x] Review every generated contact sheet, correct crops through
  `people/crop-overrides.json`, and review affected images again after recropping.
- [x] Check that image metadata, per-image credits, license terms, and modification
  notices are complete before using an image in a published puzzle.

**Done when:** all selected entries have an approved image or a documented
replacement decision, and every image intended for publication has passed visual
and attribution review.

**Completed:** all 116 selected people have reviewed 768 x 768 portraits in
`people/images`; no portraits are missing. The two feedback passes, crop fixes,
and per-image attribution are recorded in `feedback.md` and `people/metadata.json`.
`python tools\curate_people.py --verify` confirms the dataset checks.

### [x] 1. Build the offline mosaic pipeline

- [x] Add a reproducible generator that reads the reviewed portraits and produces
  target mosaics at progressively finer resolutions.
- [x] Match source-image tiles to target-image regions by average color, excluding the
  target portrait from its own tile pool.
- [x] Write versioned static assets and a manifest for each puzzle; keep target
  identities and answers out of publicly served asset metadata where practical.
- [x] Verify output dimensions, level ordering, target exclusion, and deterministic
  regeneration from the same inputs.

**Done when:** a sample target has a complete set of ordered, visually checked
mosaic levels and can be regenerated without manual image editing.

**Completed:** `tools/generate_mosaic.py` generates five ordered levels at
8, 12, 24, 48, and 96 tiles per side. The Einstein sample's five levels were
visually reviewed; the finer levels progressively reveal his face. Public assets
and private answers/provenance are separated under `puzzles`. Regeneration and
automated coverage are documented in `puzzles/README.md`.

### [x] 2. Implement the API and persistence

- [x] Create the FastAPI service and PostgreSQL schema for puzzle dates, target
  references, anonymous player identifiers (if needed), and submitted results.
- [x] Add endpoints to retrieve the daily puzzle and submit guesses/results; validate
  dates, inputs, and duplicate submissions on the server.
- [x] Keep answer validation server-side and return only the puzzle data the client
  needs to play.
- [x] Add automated tests for puzzle selection, answer matching, scoring, invalid
  input, and duplicate-result handling.

**Done when:** API tests cover the gameplay path and the service can initialize
its schema and serve a configured daily puzzle without exposing its answer.

**Completed:** `backend` provides the FastAPI service, SQLAlchemy PostgreSQL schema,
explicit initialization and offline daily-puzzle assignment commands, anonymous
cookie sessions, catalogue suggestions, server-validated guesses, persisted results,
and per-player statistics. Active games never return the answer; finished games
may reveal it. Scores and results are derived from recorded guesses, not accepted
from clients. PostgreSQL row locks and database constraints protect concurrent
submissions and retries.

All 18 API tests passed against PostgreSQL 18, including concurrent submissions.
A live HTTP smoke check initialized the schema, assigned the sample puzzle,
and preserved attempts and results across API restarts. Setup, UTC date policy,
scoring, session handling, and test commands are documented in `backend/README.md`.
Temporary validation databases and services were removed; no development database
or API server is left running.

### [x] 3. Build the browser game

- [x] Set up the React, TypeScript, and Vite frontend.
- [x] Implement the mosaic display, guess input with suggestions, incorrect-guess
  feedback, progressive levels, and a score based on the number of reveals.
- [x] Show completion or failure results and provide a shareable result that does not
  disclose the answer before the player finishes.
- [x] Make the experience usable on mobile and desktop, including keyboard
  navigation and clear loading, empty, and error states.

**Done when:** a player can complete a full puzzle on a phone or desktop and the
interface handles API errors without losing the current game state.

**Completed:** `frontend` contains the responsive React/TypeScript game with
keyboard and touch suggestions, mosaic levels, guess history, server-derived
results and statistics, spoiler-free sharing, accessible feedback, and explicit
loading, empty, API-error, and image-error states. Pending guesses retain their
idempotency UUID across retries and reloads; errors do not discard visible progress.

The production frontend build passes. Twelve mocked browser scenarios and two
live API browser runs passed at desktop/mobile viewport sizes, including real
FastAPI/PostgreSQL gameplay and reload persistence. Desktop/mobile screenshots
were visually reviewed. Setup and commands are in `frontend/README.md` (Node 22+).
Native mobile Safari and production-like routing remain step 4 verification;
temporary validation services have been stopped.

### [x] 3a. Post-MVP gameplay polish

- [x] Reveal the original portrait after each finished game (win or loss).
- [x] Allow post-game level switching by clicking the progress bar, plus a
  dedicated "Show original portrait" view.
- [x] Add a random practice mode button for unscored rounds on faces outside
  the daily answer.
- [x] Add skip actions for daily and practice rounds to reveal the next level
  without typing a name.
- [x] Improve finished-state progress controls so level-selection buttons are
  visually obvious and easier to tap.
- [x] Add a second unscored practice mode that reuses published daily mosaic
  assets (`/puzzles/.../level-*.jpg`) for side-by-side UX comparison.
- [x] Harden startup behavior by retrying initial read requests in the frontend
  during backend warm-up races.
- [x] Fix daily skip persistence bug by keeping skip request IDs within the
  `guesses.request_id` `VARCHAR(36)` database constraint.

**Done when:** finished games let players inspect every reveal level and the
original portrait, and players can start an unscored random follow-up round
without affecting daily statistics.

**Completed:** post-game level review and original-image reveal are active;
daily/practice skip is implemented and persisted; both practice variants are
available (random pixel-style and daily-mosaic-style); startup-read retry logic
reduces first-load connection interruptions after server restarts.
Backend and frontend validations passed after these changes (`backend` tests and
frontend production build/type-check).

### [x] 4. Integrate and verify the MVP

- [x] Connect the frontend to the API and static mosaic assets through the intended
  same-origin `/api/*` and static-file routes.
- [x] Test a full daily-puzzle flow, including correct and incorrect guesses,
  progressive reveals, scoring, reload behavior, and result sharing.
- [x] Check that submitted results are treated as untrusted, answer data is not
  shipped to the browser, and image credits remain available wherever images are
  redistributed or displayed.
- [x] Run the project checks and manually review representative puzzles at each
  difficulty level.

**Done when:** the end-to-end flow works with production-like configuration and
the MVP acceptance checks pass on desktop and mobile layouts.

**Completed:** same-origin routing is active in development and integration tests:
`/api/*` is proxied to FastAPI and `/puzzles/*` is served from public puzzle
assets only. Backend response contracts and tests confirm that answers and scores
are server-derived and hidden until completion, while credits links are returned
for puzzle assets.

Automated checks passed for this integration step: backend API suite (`23 tests`,
including validation and untrusted-input handling), frontend production build,
frontend browser suite (`16 passed, 2 live-only skipped`), and live API smoke
tests on desktop/mobile (`2 passed`) covering incorrect/correct guesses, reveal
progression, reload persistence, scoring, and sharing flow.

### [x] 5. Deploy and operate

**Completed:** Pixle is deployed on VPS `13.140.170.196` and served at
`https://pixle.duckdns.org` through the shared Caddy instance, while
`https://mnemo-hub.duckdns.org` remains healthy.

The deployed stack runs via Docker Compose (`db`, `api`, `frontend`) with
persistent PostgreSQL storage, production secrets in `.env.production`,
daily puzzle assignment via `backend.manage configure-puzzle`, and health checks
for all services. End-to-end verification passed on the live host:
HTTPS reachability, API health, puzzle asset serving, wrong/correct guess flow,
score calculation, and reload persistence.

Service-restart and recovery checks also passed: gameplay data remained intact
after `docker compose restart`, and a database backup/restore rehearsal succeeded
with a generated dump (`deploy/backups/pixle-*.dump`) restored through `pg_restore`.

- Prepare Pixle for deployment to the existing VPS at `13.140.170.196`,
  alongside Mnemo (`https://mnemo-hub.duckdns.org`).

- SSH access is available via `mnemo-vps`, using the dedicated
  `pixle-agent` key. Authentication uses the existing Linux user
  `mnemo-agent`, with the same permissions as the Mnemo agent.

- Inspect the existing Docker, networking, and Caddy setup before
  making changes. Do not disrupt Mnemo or overwrite its configuration.

- Prepare Docker Compose for Pixle's frontend, API, and PostgreSQL,
  including persistent storage, production secrets outside version
  control, health checks, and database backup/restore procedures.

- Prepare the Caddy configuration change for
  `https://pixle.duckdns.org`, reusing the existing Caddy instance.
  Update the Caddyfile in the Mnemo repository locally, but do not
  deploy or reload Caddy yet.

- **Pause before deploying anything to the VPS.** I will deploy the
  updated Mnemo project, including the Caddy configuration. Wait for
  my explicit confirmation before proceeding with Pixle's deployment.

- After confirmation, deploy Pixle and verify HTTPS, API
  functionality, daily puzzle selection, persistence across
  restarts, and database recovery. Confirm Mnemo remains operational.
  Run a small user test and address critical issues.

**Done when:** Pixle is deployed at `https://pixle.duckdns.org`,
persisted results survive service restarts, database recovery is
tested, and Mnemo remains fully operational.


                   Internet
                      |
              DNS: 13.140.170.196
                      |
             +------------------+
             |       VPS        |
             |  13.140.170.196  |
             |                  |
             |  Caddy :80/:443  |
             +------------------+
                      |
             HTTP Hostname prüfen
                      |
              +-------+-------+
              |               |
  mnemo-hub.duckdns.org   pixle.duckdns.org
        |                     |
        v                     v
  +-------------+       +-------------+
  | Mnemo       |       | Pixle       |
  | bestehende  |       | Frontend    |
  | Infrastruktur|      |             |
  +-------------+       +-------------+
        |                     |
    Mnemo API             Pixle API
        |                     |
    Mnemo DB              Pixle DB