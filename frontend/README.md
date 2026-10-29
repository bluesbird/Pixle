# Pixle browser game

React, TypeScript, and Vite. Requires **Node.js 22 or newer** and npm.
No external fonts, analytics, accounts, or portrait downloads are used by the UI.
For production container deployment and reverse-proxy integration, see
`DEPLOYMENT.md`.

## Run locally

Start the API on `127.0.0.1:8000` and configure today's UTC puzzle as described in
`backend\README.md`. Set `COOKIE_SECURE=false` for local HTTP development.
From the project root:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open the printed local URL. Vite proxies `/api/*` to FastAPI and serves only
`puzzles\public\` under `/puzzles/*`. The API owns sessions, attempts, scores,
answers, and history. No private manifest or target mapping is imported into
the frontend bundle.

## Build and browser checks

```powershell
npm run build
npx playwright install chromium
npm test
```

The build type-checks all frontend and test code. Browser tests run Chromium at
desktop and mobile viewport sizes, exercising keyboard suggestions, reveal
progression, winning and losing, sharing, restored progress, empty puzzles,
image failures, and interrupted requests. These tests mock the HTTP API but
load the real sample mosaic images. Native Safari/iOS testing remains part of
cross-browser integration work.

With the real API running and today's date assigned to the included Einstein
sample, also run the opt-in live browser smoke test:

```powershell
$env:PIXLE_LIVE_API = "true"
npm test -- tests/live.spec.ts
Remove-Item Env:\PIXLE_LIVE_API
```

It plays through the same-origin development routes at both viewport sizes,
reloads progress and results, and saves screenshots under ignored `test-results`.
Use an isolated development/test database, never production.

`npm run preview` previews only the built frontend. It does not configure API or
mosaic routes. Production must serve `dist`, proxy `/api/*`, and map `/puzzles/*`
to `puzzles\public\` on the same origin; that reverse-proxy setup is a later
integration/deployment step.

## Interaction and recovery

- Search is accent-insensitive. Suggestions support Up/Down, Enter to select,
  Escape to close, and touch/pointer selection. Submit with the button or Enter.
- Use **Skip** to consume one attempt without typing a name.
- The mosaic and guess history remain visible during recoverable API errors.
  Refresh retrieves authoritative server progress without discarding the input.
- A pending guess's date, text, and UUID are retained in session storage before
  sending it. A timeout or server error keeps the same UUID for retries, including
  after reload. Only the server consumes attempts; the UI never guesses a score.
  If storage is blocked, the UI warns that pending recovery is limited to the tab.
- Session identity is an HttpOnly cookie, not a local-storage identifier.
- Results show the answer only after completion. Shared text contains only the
  UTC puzzle date, attempt count, score, outcome blocks, and site origin.
  If clipboard permission is unavailable, a selectable text field is provided.
- Every puzzle links its image credits. All photos retain their individual licenses.
- Practice mode is unscored. You can test:
  - random pixel-style practice mosaics,
  - daily-mosaic-style practice that reuses published `/puzzles` levels.
