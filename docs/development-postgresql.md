# PostgreSQL Development Runbook

This runbook describes the local PostgreSQL workflow for `newQuant`.

The long-term direction is PostgreSQL as the main database for all business data, including K-line data, watch pools, alerts, trade plans, message center data, and industry GraphRAG data. SQLite remains useful for old MVP data and local backup files, but new development should validate against PostgreSQL.

## 1. Start PostgreSQL

### Option A: Docker / Colima

Install the local Docker toolchain:

```bash
brew install docker docker-compose colima
```

Start Colima:

```bash
colima start --cpu 2 --memory 4 --disk 20 --runtime docker
```

Start PostgreSQL:

```bash
cd /Users/lijiajun/ai-coding/newQuant
docker-compose -f docker-compose.dev.yml up -d postgres
```

Verify:

```bash
docker-compose -f docker-compose.dev.yml ps
docker-compose -f docker-compose.dev.yml exec postgres pg_isready -U newquant -d newquant
```

Note: on some macOS environments, the `docker compose` subcommand is unavailable while the standalone `docker-compose` command works. Prefer `docker-compose` in this repository unless the local environment proves otherwise.

### Option B: Homebrew PostgreSQL fallback

Use this path when Colima or Docker Desktop is unavailable.

```bash
brew install postgresql@16
brew services start postgresql@16
```

Create a development user and database:

```bash
/opt/homebrew/opt/postgresql@16/bin/createuser -s newquant 2>/dev/null || true
/opt/homebrew/opt/postgresql@16/bin/psql -d postgres -c "ALTER USER newquant WITH PASSWORD 'newquant';"
/opt/homebrew/opt/postgresql@16/bin/createdb -O newquant newquant 2>/dev/null || true
```

Verify:

```bash
/opt/homebrew/opt/postgresql@16/bin/pg_isready
/opt/homebrew/opt/postgresql@16/bin/psql postgresql://newquant:newquant@localhost:5432/newquant -c 'select version();'
```

## 2. Configure Backend

Set `backend/.env`:

```env
DATABASE_URL=postgresql+psycopg://newquant:newquant@localhost:5432/newquant
AUTO_INIT_DB=false
RUN_STARTUP_MIGRATIONS=false
```

Use Alembic for schema changes:

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
source venv/bin/activate
alembic upgrade head
```

Then start the backend:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 3. Migrate SQLite Data

Back up the SQLite file first:

```bash
cp /Users/lijiajun/ai-coding/newQuant/backend/data/quant.db \
  /Users/lijiajun/ai-coding/newQuant/backend/data/quant.db.backup.$(date +%Y%m%d%H%M%S)
```

Run migration:

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
source venv/bin/activate
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-url sqlite:////Users/lijiajun/ai-coding/newQuant/backend/data/quant.db \
  --target-url postgresql+psycopg://newquant:newquant@localhost:5432/newquant \
  --truncate
```

The migration summary prints:

- `source`: rows in SQLite.
- `copied`: rows inserted into PostgreSQL.
- `skipped`: legacy rows skipped during cleanup.
- `target`: rows in PostgreSQL after migration.
- `status`: `ok`, `dry_run`, `mismatch`, or `ok_with_legacy_cleanup`.

`ok_with_legacy_cleanup` is acceptable when old MVP rows contain references to records that no longer exist, such as orphan alert links.

## 4. Validation Checklist

Run backend checks:

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
./venv/bin/pytest -q
```

Run frontend checks:

```bash
cd /Users/lijiajun/ai-coding/newQuant/frontend
npm run lint
npm run build
```

Run API smoke checks:

```bash
curl http://127.0.0.1:8000/api/health
curl 'http://127.0.0.1:8000/api/messages/daily?ensure_seed=false'
curl -X POST http://127.0.0.1:8000/api/industry-reports/generate \
  -H 'Content-Type: application/json' \
  -d '{"refresh_seeds":true,"use_llm":false}'
```

## 5. Rollback

Application rollback:

1. Stop the backend.
2. Restore the previous `DATABASE_URL` in `backend/.env`.
3. Restart the backend.

Data rollback:

- PostgreSQL: restore from database backup or drop/recreate the dev database and rerun migration.
- SQLite: restore the backed-up `quant.db` file.

Do not keep SQLite and PostgreSQL as two active write databases. During migration, choose one active database for the running app.
