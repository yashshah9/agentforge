# agentforge

Multi-agent **software engineering harness**: plan → patch → **agentbox** tests → **draft PR** → human approval → audit.

## Quick start

```bash
uv venv --python 3.12
uv pip install -e ../platformkit -e ".[dev]"
uv run pytest tests/test_api.py tests/test_github.py tests/test_evals.py -q
uv run agentforge eval --min-pass-rate 1.0 --baseline evals/baseline.json
uv run agentforge serve   # :8090
# Approvals console: http://127.0.0.1:8090/approvals
```

## Docker

```bash
docker compose up --build -d agentbox redis postgres agentforge
docker compose run --rm integration
```

### Docker sandbox backend (recommended isolation)

Default compose uses agentbox **subprocess**. For ephemeral `docker run --rm` isolation:

```bash
export AGENTBOX_HOST_TMP="$(cd .. && pwd)/.agentbox-work"
mkdir -p "$AGENTBOX_HOST_TMP"
docker compose -f compose.yaml -f compose.docker-sandbox.yaml up --build -d
EXPECT_SANDBOX_BACKEND=docker \
  docker compose -f compose.yaml -f compose.docker-sandbox.yaml run --rm integration
```

`AGENTBOX_HOST_TMP` must be an absolute path bind-mounted at the same path inside the agentbox container so nested `docker run -v` works (Docker Desktop).

## GitHub draft PRs

Without credentials, PRs are `local://draft-pr/<run_id>` (fine for local/CI).

```bash
export AGENTFORGE_GITHUB_TOKEN=ghp_...          # PAT or App installation token
export AGENTFORGE_GITHUB_MIRROR_REPO=you/demos  # for fixture:// runs
export AGENTFORGE_GITHUB_BASE_BRANCH=main
```

The control plane opens a **draft** PR only. Merge requires `POST /v1/runs/{id}/approval`.

## Eval gate

```bash
agentforge eval --min-pass-rate 1.0
```

Cases live in `evals/cases.json`. CI fails if the pass rate drops.

## Docs

- [Architecture](docs/architecture.md)
- [Demo script](docs/demo.md)

## API sketch

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/runs` | enqueue a coding run |
| GET | `/v1/runs/{id}` | status, steps, draft PR, latency/cost |
| GET | `/v1/traces` | recent run traces + cost rollup |
| POST | `/v1/runs/{id}/approval` | human approve/reject |
| GET | `/v1/audit` | tenant audit trail |
