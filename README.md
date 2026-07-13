# yt-clipper-api

FastAPI service for requesting YouTube video downloads as full videos or clipped sections.
Jobs are designed to run in background workers so a future frontend can create a request,
poll its status, and download the completed file.

## Features

- Download a complete YouTube video in the best quality available through `yt-dlp`.
- Download only a bounded section using `start_seconds` and `end_seconds`.
- Process long-running jobs asynchronously with Celery and Redis.
- Persist job state in PostgreSQL through SQLAlchemy and Alembic.
- Protect API endpoints with an API key from `X-API-Key` or `Authorization: Bearer ...`.
- Expose stable JSON contracts suitable for a future frontend.
- Keep business rules isolated from FastAPI, SQLAlchemy, `yt-dlp`, and `ffmpeg`.
- Clean up the per-job download directory when a job fails before producing an output file.

## Local development

```bash
/usr/local/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

The Docker runtime exposes the `imageio-ffmpeg` bundled binary as `ffmpeg`. If you run workers
directly on the host, install `ffmpeg` locally first or ensure `imageio-ffmpeg` is available.

## Run with Docker Compose

This is the recommended way to run the project on a new machine. You only need Git and
Docker Desktop, or Docker Engine with the Docker Compose plugin.

### Option A: API only

1. Clone the repository:

```bash
git clone git@github.com:jethromx/yt-clipper-api.git
cd yt-clipper-api
```

If you do not use SSH with GitHub, clone with HTTPS instead:

```bash
git clone https://github.com/jethromx/yt-clipper-api.git
cd yt-clipper-api
```

2. Create your local environment file:

```bash
cp .env.example .env
```

3. Optional: choose where downloaded videos will be stored on the host machine:

```dotenv
DOWNLOADS_HOST_DIR=./downloads
```

For example, on macOS:

```dotenv
DOWNLOADS_HOST_DIR=/Users/you/Videos/yt-clipper
```

4. Start the API, worker, PostgreSQL, and Redis:

```bash
docker compose up --build
```

5. Open the API docs:

```text
http://localhost:8000/docs
```

Run Docker Compose from the `yt-clipper-api` directory. Running it from the parent workspace
will not find the intended compose file.

The API is available at `http://localhost:8000`, with OpenAPI docs at
`http://localhost:8000/docs`. The API service runs `alembic upgrade head` on startup.

Stop the stack with `Ctrl+C`. To remove containers and the PostgreSQL volume:

```bash
docker compose down -v
```

### Downloads folder

Downloaded videos are stored inside the container at `STORAGE_DIR` and mounted to the host
with `DOWNLOADS_HOST_DIR`.

Default values:

```dotenv
STORAGE_DIR=/app/downloads
DOWNLOADS_HOST_DIR=./downloads
```

To store videos somewhere else on the host, update `.env` before starting Compose:

```dotenv
DOWNLOADS_HOST_DIR=/Users/you/Videos/yt-clipper
```

### Full stack with the React frontend

If `yt-clipper-api` and `yt-clipper-studio` are cloned as sibling folders, this project can
orchestrate the complete stack:

1. Clone both repositories in the same parent folder:

```bash
mkdir yt-clipper
cd yt-clipper
git clone git@github.com:jethromx/yt-clipper-api.git
git clone git@github.com:jethromx/yt-clipper-studio.git
```

If you do not use SSH with GitHub, clone with HTTPS instead:

```bash
mkdir yt-clipper
cd yt-clipper
git clone https://github.com/jethromx/yt-clipper-api.git
git clone https://github.com/jethromx/yt-clipper-studio.git
```

2. Create the backend `.env` file:

```bash
cd yt-clipper-api
cp .env.example .env
```

3. Review these values in `.env`:

```dotenv
API_KEYS=dev-secret-change-me
FRONTEND_API_KEY=dev-secret-change-me
PUBLIC_API_BASE_URL=http://localhost:8000
FRONTEND_PORT=8080
DOWNLOADS_HOST_DIR=./downloads
```

`FRONTEND_API_KEY` must match one of the values in `API_KEYS`.

4. Start the complete stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.full.yml up --build
```

Services exposed by default:

- API: `http://localhost:8000`
- Frontend: `http://localhost:8080`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

5. Open the frontend:

```text
http://localhost:8080
```

Useful `.env` parameters:

```dotenv
ENV_FILE=.env
API_KEYS=dev-secret-change-me
API_PORT=8000
FRONTEND_PORT=8080
PUBLIC_API_BASE_URL=http://localhost:8000
FRONTEND_API_KEY=dev-secret-change-me
DOWNLOADS_HOST_DIR=./downloads
```

`PUBLIC_API_BASE_URL` must be reachable from the user's browser, not only from inside Docker.
For local use, `http://localhost:8000` is usually correct.
If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB`, update `DATABASE_URL`
with the same values.

## API examples

These examples assume the default API key from `.env.example`.

Create a full-video download:

```bash
curl -X POST http://localhost:8000/api/v1/downloads \
	-H 'X-API-Key: dev-secret-change-me' \
	-H 'Content-Type: application/json' \
	-d '{"source_url":"https://www.youtube.com/watch?v=VIDEO_ID"}'
```

Create a clipped download:

```bash
curl -X POST http://localhost:8000/api/v1/downloads \
	-H 'X-API-Key: dev-secret-change-me' \
	-H 'Content-Type: application/json' \
	-d '{"source_url":"https://www.youtube.com/watch?v=VIDEO_ID","start_seconds":30,"end_seconds":75}'
```

Poll job status:

```bash
curl -H 'X-API-Key: dev-secret-change-me' \
	http://localhost:8000/api/v1/downloads/JOB_ID
```

Download the completed file:

```bash
curl -L -H 'X-API-Key: dev-secret-change-me' \
	-o video.mp4 \
	http://localhost:8000/api/v1/downloads/JOB_ID/file
```

The file endpoint is protected like the rest of the API. Browser links must send
`X-API-Key`; the React frontend does this with an authenticated `fetch` request.

## Quality checks

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest
```

Coverage is configured to fail below 85%.

## Architecture

- `domain`: entities, value objects, statuses, and business exceptions.
- `application`: use cases and ports.
- `infrastructure`: implementations for SQLAlchemy, Celery, local storage, `yt-dlp`, and `ffmpeg`.
- `interfaces/http`: FastAPI schemas, dependencies, and routes.

## Legal note

Use this service only for content you own, content with a compatible license, or content
you are otherwise allowed to download. The service does not bypass DRM or access controls.

## YouTube download notes

The `yt-dlp` adapter uses browser-like headers, retries, and alternate YouTube clients to
reduce transient `403 Forbidden` failures. Some videos may still require cookies, login,
age verification, regional access, or may be blocked by YouTube rate limits.

## Troubleshooting

- `docker compose` fails from the parent folder: run the command from `yt-clipper-api`.
- Ports already in use: change `API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, or `FRONTEND_PORT` in `.env`.
- Frontend receives `Invalid or missing API key`: make `FRONTEND_API_KEY` match `API_KEYS` and restart Compose.
- Videos are not where expected: check `DOWNLOADS_HOST_DIR`; that host folder is mounted into `STORAGE_DIR` in the containers.
- Persistent YouTube `403 Forbidden`: try another video first. Some videos require cookies, login, age verification, or regional access.