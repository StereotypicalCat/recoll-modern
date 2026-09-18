# Architecture

How `recoll-modern` is built today. Update in the same commit as any structural change.

## Overview

**Nothing is built yet.** This file records intent, the design questions that are now closed, and the
Recoll behaviour verified against a real container. Do not read "Intended shape" as describing existing
code.

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

## Delivery order

The product is four specs, built in order. Each gets its own spec, plan and review cycle.

| Spec | Scope |
|---|---|
| 001 Search engine + API | Recoll in Docker, single index, per-file collection membership, collection CRUD, indexing job queue, search endpoint, authentication |
| 002 Web UI | Blocked on `/impeccable init` replacing the `PRODUCT.md` stub, then `DESIGN.md` |
| 003 MCP server | Thin wrapper over 001's HTTP API |
| 004 Multi-user management | Roles, user CRUD, per-collection permissions |

## Intended shape

- **One** Recoll index for all documents, not one per collection. Collection membership is per-file
  metadata, not directory layout, so two files in the same directory can belong to different
  collections.
- A Python service owns Recoll through its native Python bindings (`from recoll import recoll`).
- SQLite holds collections, membership, indexing jobs, users and sessions.
- An HTTP API consumed by both the web UI and the MCP server, so the two never diverge.
- A Docker image containing Recoll itself, plus compose wiring for document volumes and index storage.

## Verified Recoll mechanics

Established empirically on 2026-09-18 in a throwaway `debian:trixie-slim` container running
Recoll 1.43.0 / Xapian 1.4.29. Re-verify if the Recoll major version changes.

- **Per-file metadata is indexable and queryable.** A `fields` file declaring
  `[xattrtofields] collection = collection`, `[prefixes] collection = XYCOLL` and `[stored] collection =`
  makes the `user.collection` extended attribute a queryable field (`collection:<value>`), returned on
  each result. Recoll strips the `user.` prefix itself.
- **Multi-membership works.** A space-separated xattr value puts one file in several collections. An
  `OR` across collections returns it **once**, in a single coherently ranked result set — Xapian does
  the ranking, so no application-side merging is needed.
- **A plain incremental `recollindex` does not see xattr-only changes.** It compares mtime, and
  `setfattr` does not change mtime; `touch` does not help either. `recollindex -i <file>` does pick the
  change up, in roughly 20ms for one file. Retagging therefore costs one file, never a rebuild.
- **The field value is tokenised and matched case-insensitively.** A tag of `cook-books` is matched by
  `collection:cook` *and* `collection:books`; `TechBooks` is matched by `collection:techbooks`. Using
  human-readable collection names as tags would let collections silently bleed into one another.
- **An unscoped query returns every document, including untagged ones.** Recoll will not enforce
  collection scoping; the API layer must.

## Open design questions

Closed by the 001 brainstorm (2026-09-18) — see `docs/DECISIONS.md` for the reasoning:

1. ~~Collection isolation~~ — one index; membership is an opaque collection ID in a `user.collection`
   xattr; human names live only in SQLite.
2. ~~Cross-collection search~~ — allowed, but only when explicitly requested. Ranking is Xapian's.
3. ~~Indexing trigger~~ — an in-process job queue, backed by SQLite.
4. ~~Stack~~ — Python + FastAPI, managed with `uv`.
5. ~~Auth and exposure~~ — real authentication in 001; user administration deferred to 004.
6. ~~Result presentation~~ — metadata plus Recoll snippets; full text and file download are separate
   endpoints.

Still open, to be closed by the remaining sections of the 001 design:

- Component boundaries and the SQLite schema.
- API surface, pagination, and error semantics.
- Test strategy, including how tests skip when the container is down.

## External dependencies

| Dependency | What breaks without it |
|---|---|
| Recoll (in-container) | All indexing and search. Not installed on the host — see `AGENTS.md` Rules. |
| Docker + compose | The only supported way to run the service. |
| Document volumes | Nothing to index; collections resolve to empty. |
| Extended-attribute support on the document volume | Collection membership. Without xattrs every document is untagged and every scoped search returns nothing — a silent failure, so it must be checked at startup. |

## Invariants

- A query never silently spans collections: the scope is an explicit, required parameter, and the API
  refuses a search that does not name one.
- Collection identity in the index is an opaque single-token ID, never a user-supplied name, so
  collections cannot bleed into one another and renaming never touches the index.
- Indexed content is never written into the repository.

## Known rough edges

None yet — nothing has been built. Cross-linked backlog: `docs/TODO.md`.
