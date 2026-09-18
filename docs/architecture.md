# Architecture

## Trust boundaries

```
┌──────────────────────────── control plane (trusted) ──────────────────────────┐
│  API ──► queue ──► worker/pipeline                                              │
│    │         policy (prompt injection, path allowlist)                         │
│    │         audit (platformkit)                                               │
│    └──► GitHub API (token stays here) ── draft PR only                         │
└───────────────────────────────────────┬────────────────────────────────────────┘
                                        │ embed sources + run unittest
                                        ▼
                          ┌── agentbox sandbox (untrusted) ──┐
                          │  no GitHub token                 │
                          │  network isolation when host OK  │
                          └──────────────────────────────────┘
```

## Run state machine

`queued → planning → coding → testing → awaiting_approval → done|failed`

Merge never happens automatically. Approval is an explicit API call after the draft PR exists.

## Draft PR publishing

| Mode | When | Result |
|------|------|--------|
| `local` | no `AGENTFORGE_GITHUB_TOKEN` | `local://draft-pr/<run_id>` |
| `github` | token set | branch `agentforge/<id>` + **draft** PR via Git Data API |

For `fixture://` runs, set `AGENTFORGE_GITHUB_MIRROR_REPO=owner/repo` so patches land on a real repository.

Token sources: classic/fine-grained PAT, or a GitHub App **installation token** minted outside the process and passed as `AGENTFORGE_GITHUB_TOKEN`.

## Worker

`agentforge serve` starts an **inline daemon worker** via FastAPI lifespan (`AGENTFORGE_INLINE_WORKER=true` by default). Burst `POST /v1/runs` is drained automatically in one process.

Set `AGENTFORGE_INLINE_WORKER=false` for deterministic tests that call `process_once` / `drain` explicitly. Docker compose uses the same serve entrypoint (Redis queue + inline worker).

## Observability

Every pipeline run records:

- per-step `latency_ms`
- total `latency_ms` + `estimated_cost_usd` (flat sandbox metering today)
- `GET /v1/traces` for tenant rollups

## Eval gate

`evals/cases.json` drives offline golden scenarios (happy path, policy deny, sandbox fail, unknown fixture).

```bash
agentforge eval --min-pass-rate 1.0 --baseline evals/baseline.json
# refresh snapshot after intentional pipeline changes:
agentforge eval --write-baseline evals/baseline.json
```

CI fails when the pass rate drops or a previously-passing case regresses.
