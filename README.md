# agentforge

Multi-agent **software engineering harness**: plan → patch fixture repo → **agentbox** tests → draft PR placeholder → human approval → audit.

## Docker (recommended)

```bash
cd agentforge
docker compose up --build -d agentbox redis postgres agentforge
docker compose run --rm integration
```

Stack: `agentforge` + `agentbox` + Redis queue + Postgres audit.

## Local (unit/functional, mocked sandbox)

```bash
uv venv --python 3.12
uv pip install -e ../platformkit -e ".[dev]"
uv run pytest tests/test_api.py -v
```

## Manual API

```bash
curl -s localhost:8090/health
curl -s -X POST localhost:8090/v1/runs \
  -H "Authorization: Bearer dev-key" \
  -H "Content-Type: application/json" \
  -d '{"issue":"Fix the off-by-one bug in increment","repo_url":"fixture://broken_counter"}'
```

## Scenarios covered

| Scenario | Where |
|----------|--------|
| Auth missing / invalid | unit |
| Tenant isolation | unit + docker |
| Happy path fix + approve | unit (mock) + docker (live agentbox) |
| Reject approval | unit |
| Sandbox test failure | unit |
| Prompt-injection policy deny | unit + docker |
| Unknown fixture | unit |
| Redis queue + Postgres audit | docker |
