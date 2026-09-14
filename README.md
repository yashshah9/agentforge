# agentforge

Multi-agent **software engineering harness**: plan → patch → **agentbox** tests → **draft PR** → human approval → audit.

## Quick start

```bash
uv venv --python 3.12
uv pip install -e ../platformkit -e ".[dev]"
uv run pytest tests/test_api.py tests/test_github.py tests/test_evals.py -q
uv run agentforge eval --min-pass-rate 1.0
uv run agentforge serve   # :8090
```

## Docker

```bash
docker compose up --build -d agentbox redis postgres agentforge
docker compose run --rm integration
```

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
| GET | `/v1/runs/{id}` | status, steps, draft PR |
| POST | `/v1/runs/{id}/approval` | human approve/reject |
| GET | `/v1/audit` | tenant audit trail |
