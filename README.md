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

```bash
cp .env.example .env
docker compose up --build
```

Run Docker Compose from this `yt-clipper-api` directory. Running it from the parent
workspace will not find the intended compose file.

The API is available at `http://localhost:8000`, with OpenAPI docs at
`http://localhost:8000/docs`. The API service runs `alembic upgrade head` on startup.

## API examples

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