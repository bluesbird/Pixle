# Pixle API

FastAPI with SQLAlchemy and PostgreSQL. All gameplay state is server-side; there
is no endpoint accepting a claimed score, attempt count, win, or arbitrary result.
Daily games persist in PostgreSQL; practice rounds are held in memory and lost
on API restart. Completing a daily game records exactly one result.
For production container deployment and backup/restore procedures, see
[`DEPLOYMENT.md`](../DEPLOYMENT.md).

## Set up PostgreSQL and assign a daily puzzle

Create a PostgreSQL database and user, then run from the project root:

```powershell
python -m pip install -r requirements-api.txt
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/pixle"
python -m backend.manage migrate
$env:COOKIE_SECURE = "false"
python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000
```

All daily boundaries are **UTC**. Missing dates are auto-assigned on first access
using a deterministic shuffled cycle over all available targets: one unique portrait
per day for the full cycle length (currently 200), then a new shuffled cycle begins.
Future puzzles are never returned, and guesses are accepted only for the current UTC
date. Optional environment variables:

- `PUZZLE_CYCLE_START_DATE=YYYY-MM-DD` to pin cycle day 1 (defaults to the earliest
  configured puzzle date; if none exists, the first auto-assigned date).
- `PUZZLE_CYCLE_SEED=<string>` to control shuffle deterministically across deploys.

`configure-puzzle` remains available as an explicit override for a specific date.
Repeating an identical assignment is safe; changing a date's puzzle or changing
existing catalogue identities is rejected.

`migrate` is Alembic-backed and safe for both fresh and already-initialized
databases:

- Empty database: applies all migrations to `head`.
- Existing Pixle schema without `alembic_version`: stamps to `head` once, then
  applies future migrations.
- Versioned database: applies pending migrations only.

Management commands:

```powershell
python -m backend.manage migrate
python -m backend.manage make-migration --message "add foo" --autogenerate
python -m backend.manage stamp-head
```

`init-db` remains available for explicit legacy bootstrap workflows, but runtime
startup now uses `migrate`.

Explicit puzzle configuration imports the private offline manifest and reviewed catalogue,
verifies public asset hashes and provenance, and stores the target reference and
ordered levels in PostgreSQL. At runtime, the API reads catalogue metadata,
`puzzles\private\targets.json`, and public manifests for automatic assignment.
Original portraits are used for pixelated practice and served through
`/api/people/{person_id}/photo`; that route is public. The source directories
are not mounted as static files.

## Routes and gameplay contract

| Route | Purpose |
|---|---|
| `GET /api/health` | Database connectivity |
| `POST /api/session` | Create or reuse an anonymous session |
| `GET /api/people` | Full catalogue of `{id, name}` suggestions, no target flags |
| `GET /api/people/{person_id}/photo` | Public original portrait by person ID |
| `GET /api/puzzles/daily` | Today's puzzle and this player's persisted progress |
| `GET /api/puzzles/YYYY-MM-DD` | Available puzzle and this player's progress |
| `GET /api/puzzles/YYYY-MM-DD/original` | Daily original portrait, requiring a completed game |
| `POST /api/puzzles/YYYY-MM-DD/guesses` | Validate a guess and advance the game |
| `POST /api/puzzles/YYYY-MM-DD/skip` | Consume one attempt and reveal the next level |
| `POST /api/practice/random` | Start an unscored pixelated portrait round |
| `POST /api/practice/mosaic` | Start an unscored random practice round using available pre-generated mosaic levels |
| `GET /api/practice/{practice_id}` | Retrieve the current practice game state |
| `POST /api/practice/{practice_id}/guesses` | Submit a practice guess |
| `POST /api/practice/{practice_id}/skip` | Skip to the next practice level |
| `GET /api/practice/{practice_id}/level-{n}.jpg` | Authenticated practice mosaic image |
| `GET /api/practice/{practice_id}/original` | Practice original portrait, requiring a completed game |
| `GET /api/stats/me` | Completed games, wins, total score for this session |

Puzzle, guess, and stats routes require the session cookie. Session creation
sets an opaque, HttpOnly, SameSite=Lax cookie scoped to `/api`, retained for one
year. Only its SHA-256 hash is stored; no IP address is used as an identifier.
Keep the cookie between requests and reloads. Clearing it loses access to that
anonymous history; there is no account recovery or cross-device identity.
An invalid existing cookie returns 401; clear it before creating a new session.

Cookies default to Secure. For local HTTP development only:

```powershell
$env:COOKIE_SECURE = "false"
```

Deploy behind same-origin HTTPS, with `/api/*` proxied to FastAPI and `/puzzles/*`
mapped to **`puzzles\public\` only**. Static asset serving is the reverse proxy's
responsibility; this service does not mount the repository. Public manifests and
guessable finer-level URLs are not a cheat-proof reveal boundary.
Keep linked image credits accessible in the UI.

Example request body (use a new UUID for every distinct guess):

```json
{"guess": "Beyonce", "request_id": "42ab56ce-d9cb-4864-a95f-d50d655b061e"}
```

Use the suggested name or ID. Matching ignores case, accents, punctuation, and
spacing, and also accepts the catalogue's Wikipedia title. No fuzzy matching or
ambiguous surname matching is performed. Unknown names return 422 and do not
consume attempts. Repeating a person with a different UUID returns 409. Replaying
the same UUID and person is idempotent and returns current progress; reusing the
UUID for a different person returns 409. Extra request fields are rejected.

Each incorrect guess advances one level. The skip endpoints also advance exactly
one level without requiring a typed name, and record that turn as `Skipped`.
There is one attempt per level (five for the sample). A correct guess earns
`(max_attempts - attempts + 1) * 100`;
exhausting attempts earns zero. The server derives every value. Results are
created atomically with the terminal guess. Further guesses return 409.
The answer and score appear only after this player's game is finished.
Responses are not cacheable. Database errors are logged and return 503.

Practice mode is unscored and does not update `/api/stats/me`. Random practice
creates five authenticated pixelated images generated from the selected portrait
at progressively finer block sizes. Mosaic practice reuses pre-generated
`/puzzles/.../level-*.jpg` assets chosen at random from the local puzzle set.

PostgreSQL row locks on the player serialize concurrent guesses, including the
first guess, and uniqueness constraints enforce one game per player/date, one
request ID per game, one guess per person/game, and one result per game.
Anonymous users can still reset cookies to start another identity; this MVP
does not claim to prevent that. Rate limiting and deployment hardening belong
with deployment work, not client-side score validation.

## Validation

```powershell
python -m unittest discover -s backend\tests -v
```

Without a database setting, tests explicitly use temporary SQLite databases.
They exercise the HTTP gameplay path, catalogue import, PostgreSQL DDL compilation,
answer matching, scoring, dates, session isolation, persistence, invalid input,
replays, and duplicate results. SQLite does not implement PostgreSQL row locks.
To run the same suite including concurrency against a dedicated PostgreSQL database:

```powershell
$env:PIXLE_TEST_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/pixle_test"
python -m unittest discover -s backend\tests -v
```

Tests create uniquely named schemas and drop only those schemas afterwards. The
test database user needs schema creation rights. Never point tests at production.
Three concurrency checks require PostgreSQL and are skipped unless
`PIXLE_TEST_DATABASE_URL` is configured.
For an explicitly local smoke test without PostgreSQL, set `DATABASE_URL` to
`sqlite:///pixle-local.db`; this is not the production backend or a concurrency
substitute.
