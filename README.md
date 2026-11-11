# Cinema Diary

A private movie-taste diary, built to learn agentic AI tooling end to end:
MCP, goose, AGENTS.md, Ollama, A2A and agentgateway. A learning and
portfolio project, not a product.

Loop: stated taste → curated list → log what I watch (tap-only review)
→ dashboard → suggestions that match my taste → repeat.

## Status
- [x] **P1 — Data + access control**: PocketBase schema as migrations, invite-only
      users, service account for the importer, rerun-safe TMDB import
- [ ] P2 — Taste onboarding, curated list, watch log, dashboard
- [ ] P3 — MCP server + goose
- [ ] P4 — AGENTS.md + goose builds a feature
- [ ] P5 — Ollama: learned taste, ranking, reasons
- [ ] P6 — A2A agents: Scout + Critic
- [ ] P7 — agentgateway in front

## Architecture (P1)
    TMDB API ──(bearer token, throttled)──► importer.py ──(service account)──► PocketBase
                                                                             ├─ movies
                                                                             ├─ people
                                                                             └─ credits (who did what on which film)

- **Access control first**: every API rule requires a logged-in caller; only the
  `service_accounts` identity can write movie data; only superusers can delete.
- **Schema as code**: `pb_migrations/` is committed; `pb_data/` never is.
- **Rerun-safe import**: record ids are derived from TMDB ids
  (sha256 → 15 chars), so re-running converges instead of duplicating.

## Run it
    make serve                      # PocketBase 0.40.6 on 127.0.0.1:8090
    set -a; source .env; set +a     # see .env.example
    uv run python -m cinema_diary.importer "Satyajit Ray" "Mani Ratnam"
    make check                      # ruff + pytest

PocketBase is pinned at v0.40.6: its GitHub repo was archived in Oct 2026.

## Write-ups
- [P1 — what I learned](docs/p1-what-i-learned.md)

## Credits
Movie data from [TMDB](https://www.themoviedb.org).
This product uses the TMDB API but is not endorsed or certified by TMDB.
