# Architecture

How `recoll-modern` is built today. Update in the same commit as any structural change.

## Overview

**Nothing is built yet.** This file currently records intent and the open questions that the first
spec must close. Do not read anything below "Intended shape" as describing existing code.

The goal: a self-hosted service that wraps Recoll's indexing and full-text search behind (a) a modern
web UI and (b) an MCP server, running in Docker, with several independent collections such as
`techbooks` and `cookbooks`.

## Map

| Path | Responsibility |
|---|---|
| `AGENTS.md` | Agent rules; single source of truth |
| `PRODUCT.md` | Durable product context for the `impeccable` skill |
| `docs/specs/`, `docs/plans/` | Approved specs and implementation plans |

No source directories exist yet. Add rows here as they appear.

## Intended shape

Not yet decided or validated. The pieces the spec has to place:

- A Recoll layer that owns indexing and querying, per collection.
- An HTTP API consumed by both the web UI and the MCP server, so the two never diverge.
- An MCP server exposing search (and likely collection listing) as tools.
- A Docker image that contains Recoll itself, plus compose wiring for document volumes and index storage.

## Open design questions

The first spec must answer these. None are settled.

1. **Collection isolation.** Recoll's model is a config directory per index (`RECOLL_CONFDIR`).
   Confirm against Recoll's own docs, then decide: one config dir per collection, and what owns the
   mapping from collection name to config dir and document root.
2. **Cross-collection search.** Allowed at all? If yes, merged ranking across separately-scored indexes
   is not free — decide before building the UI around it.
3. **Indexing trigger.** Cron inside the container, Recoll's real-time monitor, or API-triggered runs.
   Affects whether the container needs a long-running process beyond the web server.
4. **Stack.** Unchosen. See `AGENTS.md` Commands for what this host actually has installed.
5. **Auth and exposure.** Whether the service authenticates at all, or assumes a reverse proxy does it.
6. **Result presentation.** Recoll returns snippets and can extract/preview documents; decide how much
   of that the API surfaces, since it drives both the UI and the MCP tool shape.

## External dependencies

| Dependency | What breaks without it |
|---|---|
| Recoll (in-container) | All indexing and search. Not installed on the host — see `AGENTS.md` Rules. |
| Docker + compose | The only supported way to run the service. |
| Document volumes | Nothing to index; collections resolve to empty. |

## Invariants

To be established with the first code. Candidates the spec should confirm and then record here:
a query never silently spans collections; indexed content is never written into the repository.

## Known rough edges

None yet — nothing has been built. Cross-linked backlog: `docs/TODO.md`.
