# recoll-modern

A modern web UI and MCP server layered on Recoll full-text search: self-hosted via Docker, managing
several independent collections (e.g. `techbooks`, `cookbooks`).

**Status:** obsolete and archived — superseded by Knowledgenet (see README). Spec 001's search API and
Docker deployment are implemented; the planned web UI, MCP server, and multi-user specs will not be built.

`AGENTS.md` is the single source of truth for agents here. `CLAUDE.md` and `GEMINI.md` only point here.
On demand: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/TODO.md`, `PRODUCT.md`.

## Commands

install: `uv sync --locked`
dev: `uv run recoll-modern`
test: `uv run pytest`
single-test: `uv run pytest path/to/test.py::test_name -v`
lint: `uv run ruff check .`
typecheck: `uv run mypy src tests`
build: `uv build`

Installed on this host: `docker` 29.5.2 with `docker compose`, `node` 20.19.2, `npm` 9.2.0, `bun` 1.3.14,
`yarn` 1.22.22, `python3` 3.13.5, `uv` 0.12.16 (in `~/.local/bin`, already on `PATH`), `dotnet` 10.0.302.
**Absent: `pnpm`, `poetry`, `go`, `cargo`** — do not write commands that assume them.
`uv` is the package manager for this project; do not use bare `pip`, `venv`, or `poetry`.

## Rules

- `recoll`, `recollindex`, and `recollq` are **not installed on this host** — they exist only inside the
  container. Never invoke them directly; go through the container. Tests needing them must skip when it
  is down, not fail.
- The remote is **Gitea** (`gitea.lucaswinther.info`), not GitHub. `gh` does not work here — no
  `gh pr create`, no `gh issue`. Use `git` plus the Gitea web UI.
- Indexed documents and Recoll config directories are user data: never committed, never deleted to
  "reset" state.

## Workflow

Required skills: `superpowers`, `impeccable`. Installed per-machine, never committed — check at session
start, install if missing:
`/plugin marketplace add obra/superpowers-marketplace` then `/plugin install superpowers@superpowers-marketplace`
`npx impeccable install`

Specs -> `docs/specs/NNN-slug.md`. Plans -> `docs/plans/NNN-slug.md`, numbered to match its spec.
**This overrides the superpowers defaults** (`docs/superpowers/specs/`, `docs/superpowers/plans/`,
date-named). Without this line, artefacts scatter into a second tree.

Anything beyond a trivial fix: brainstorm -> spec (sign-off) -> plan (sign-off) -> TDD -> review.
TDD means failing test first, watch it fail, minimal code, watch it pass, commit.
Tick plan checkboxes as you go so an interrupted session is resumable.
Trivial changes (typo, version bump, one-line config): say "trivial, skipping spec" and proceed.

Use `impeccable` for user-facing UI — `shape` before building, `audit`/`polish` on existing, `harden`
before shipping. Product context: `PRODUCT.md` (a stub: run `/impeccable init` before the first UI work).
There is no `DESIGN.md` yet; the first UI build writes one, and after that never hand-roll around its tokens.

## Architecture

`docs/ARCHITECTURE.md` describes the implemented service and delivery order. Its original six design
questions were closed in spec 001; read it before proposing new structure.

## Boundaries

Branch before touching `main`; it currently has no history beyond the bootstrap commit.

Ask first: choosing or changing the stack · new runtime dependencies · schema or public API changes ·
auth and how the service is exposed · deleting or rebuilding a Recoll index · work the approved plan
does not cover.

If the task turns out much larger than the plan assumed: stop, report, re-plan.

## Docs duties

Same commit as the code, not "later":
- `docs/ARCHITECTURE.md` — when a module, boundary, or data flow changes.
- `docs/DECISIONS.md` — append-only; any choice a future maintainer would reverse-engineer.
- `docs/TODO.md` — anything noticed and deliberately not fixed. No `TODO` comments in source.

## Git

Branches: `feat|fix|chore/<slug>`. Commits: Conventional Commits. There was no history before the
bootstrap commit, so this line *is* the convention.

## Done means verified

Do not report success on work you have not run. Before saying done: tests run *in this session* and seen
passing · lint and typecheck clean · matches the approved spec · docs duties complete · `git status`
clean and the diff is only what you intended. "It should work" is not verification.
