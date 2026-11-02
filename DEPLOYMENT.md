# Pixle deployment and operations

Docker Compose runs:

- `frontend` (static React build served on host port `18080`)
- `api` (FastAPI on host port `18000`)
- `db` (PostgreSQL with persistent volume)

It is designed to be fronted by the **existing VPS Caddy instance**.
When Caddy runs in Docker, `host.docker.internal` needs access to Pixle's host
ports; keep host firewall rules restrictive so only intended public paths are exposed.

## 1. Prepare secrets and files on the VPS

From the Pixle repo root on the VPS:

```sh
cp .env.production.example .env.production
chmod 600 .env.production
mkdir -p /opt/mnemo/Mnemo/deploy/pixle-public
cp -r puzzles/public/* /opt/mnemo/Mnemo/deploy/pixle-public/
```

Edit `.env.production` and replace every placeholder password.

## GitHub Actions deployment secrets

The workflow at `.github/workflows/ci.yml` deploys `main` automatically after
backend and frontend checks pass. Configure these repository secrets:

- `PIXLE_ACTIONS_SSH_KEY` (private key for your `pixle-actions` SSH user/key)
- `VPS_KNOWN_HOSTS` (output of `ssh-keyscan -H <your-host>`)
- `VPS_HOST` (for example `your-vps.example.org`)
- `VPS_USER` (SSH user on the VPS)
- `VPS_REPO_PATH` (absolute path to Pixle checkout on the VPS)
- `PIXLE_PUBLIC_DIR` (absolute path served by Caddy for `/puzzles/*`,
  for example `/opt/mnemo/Mnemo/deploy/pixle-public`)

## 2. Start and verify the Pixle stack

```sh
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d
docker compose --env-file .env.production ps
```

Health checks must report `healthy` for `db`, `api`, and `frontend`.
The API container runs `python -m backend.manage migrate` at startup before
launching Uvicorn.

API smoke checks:

```sh
curl --fail http://127.0.0.1:18000/api/health
curl --fail http://127.0.0.1:18080/
```

## 3. Configure Caddy for pixle.duckdns.org

Use the snippet in `deploy/Caddyfile.pixle.snippet` and merge it into the
Mnemo repository Caddyfile:

- `/api/*` -> `host.docker.internal:18000`
- `/puzzles/*` -> `/opt/mnemo/Mnemo/deploy/pixle-public` (via `handle_path`)
- everything else -> `host.docker.internal:18080`

Validate the shared Caddy configuration before reloading it. Preserve the existing
Mnemo routes.

## 4. Configure automatic daily scheduling

Daily puzzles are auto-assigned on first access in UTC, one unique portrait per
cycle (currently 200 days), then reshuffled for the next cycle. Set a stable
cycle start and seed in `.env.production`:

```sh
PUZZLE_CYCLE_START_DATE=2026-10-29
PUZZLE_CYCLE_SEED=pixle-production-v1
```

Recreate the API container after changing these values:

```sh
docker compose --env-file .env.production up -d api
```

You can still pin a specific date manually if needed:

```sh
docker compose --env-file .env.production exec api python -m backend.manage configure-puzzle --date YYYY-MM-DD --asset-id bbde88819742bd384112a358
```

Replace `YYYY-MM-DD` with an unassigned date. The asset ID above is the included
Einstein example; other current IDs are listed in `puzzles/private/targets.json`.

## 5. Backup and restore runbook

Create backup:

```sh
chmod +x deploy/backup-db.sh deploy/restore-db.sh
./deploy/backup-db.sh
```

Restore backup:

```sh
./deploy/restore-db.sh deploy/backups/pixle-YYYYMMDDTHHMMSSZ.dump
```

Post-restore verification:

```sh
curl --fail http://127.0.0.1:18000/api/health
docker compose --env-file .env.production restart api
curl --fail http://127.0.0.1:18000/api/health
```

## 6. Post-deploy acceptance checks

After updating Caddy:

1. Open `https://pixle.duckdns.org` on desktop and mobile.
2. Confirm daily puzzle loads and `/puzzles/.../level-*.jpg` is reachable.
3. Confirm guess flow, scoring, and reload persistence.
4. Restart Pixle services (`docker compose --env-file .env.production restart`) and verify daily progress remains.
5. Run one backup and one restore rehearsal in a maintenance window.
6. Confirm `https://mnemo-hub.duckdns.org` remains healthy.
