# Architecture

How `recoll-modern` is built today. Update in the same commit as any structural change.

## Overview

The Python service scaffold, SQLite schema, collection and membership repositories, document
discovery/identity modules, durable job worker, engine adapter, authentication service, and initial
HTTP shell, membership routes, job routes, scoped search, document retrieval, and Docker packaging are
built and covered by host and container acceptance tests. Recoll behaviour
below was verified against a real container.

The goal: a self-hosted service that wraps Recoll's indexing and full-text search behind (a) a modern
web UI and (b) an MCP server, running in Docker, with several independent collections such as
`techbooks` and `cookbooks`.

## Map

| Path | Responsibility |
|---|---|
| `AGENTS.md` | Agent rules; single source of truth |
| `PRODUCT.md` | Durable product context for the `impeccable` skill |
| `docs/specs/`, `docs/plans/` | Approved specs and implementation plans |
| `src/recoll_modern/` | Python service package; configuration, application factory and CLI boundary |
| `src/recoll_modern/indexing/` | Root-relative path policy, read-only discovery, stable file hashing |
| `src/recoll_modern/storage/` | SQLite migrations, collection metadata and content-hash identity |
| `src/recoll_modern/domain/membership.py` | Validates sources and applies direct additions and rule changes |
| `src/recoll_modern/indexing/reconcile.py` | Refreshes persistent directory rules while retaining excluded or unreadable files as present |
| `src/recoll_modern/indexing/worker.py` | Claims one durable job at a time and runs blocking handlers off the event loop |
| `src/recoll_modern/indexing/handlers.py` | Scans membership sources before strict-mode mutations and records file errors |
| `src/recoll_modern/indexing/map_export.py` | Writes a durable atomic map from canonical paths to opaque collection IDs |
| `helper/` | C reader run by Recoll's `metadatacmds` for each indexed file |
| `Dockerfile`, `compose.yaml`, `docker/` | Non-root Recoll runtime, read-only document mount, persistent state/index volumes and config templates |
| `compose.published.yaml` | Pull-only deployment with the same runtime settings and persistent mounts |
| `.gitea/workflows/image.yaml`, `scripts/image_tags.py`, `scripts/publish_image.sh` | CI checks and Gitea registry publication; Git refs select published tags |
| `src/recoll_modern/engine/` | Shared Protocol, deterministic fake, and isolated Recoll Python/indexer adapter |
| `src/recoll_modern/domain/auth.py`, `storage/auth.py` | Argon2 password checks, seeded administrator, hashed server-side sessions and CSRF verification |
| `src/recoll_modern/api/` | HTTP auth, health, file browsing, collection/membership/rule/job resources, search, document retrieval, prefix/proxy handling and JSON errors |
| `src/recoll_modern/domain/search.py` | Validates explicit scope and fields, projects current SQLite identities and membership onto engine-ranked hits |
| `tests/` | Automated service tests |
| `tests/contract/`, `tests/integration/`, `tests/security/` | Requirement matrix, real-container Recoll contract, lifecycle, and boundary checks |

Discovery produces content hashes and root-relative paths without writing to the document volume.
The document repository records these in one transaction, chooses the smallest live path as canonical,
and marks paths missing only when a caller explicitly reconciles them.

## Delivery order

The product is five specs, built in order. Each gets its own spec, plan and review cycle. Spec 005 is a
future distribution track and starts only after the hosted product through 004 is delivered.

| Spec | Scope |
|---|---|
| 001 Search engine + API | Recoll in Docker, single index, per-file collection membership, collection CRUD, indexing job queue, search endpoint, authentication |
| 002 Web UI | Blocked on `/impeccable init` replacing the `PRODUCT.md` stub, then `DESIGN.md` |
| 003 MCP server | Thin wrapper over 001's HTTP API |
| 004 Multi-user management | Roles, user CRUD, per-collection permissions |
| 005 Cross-platform desktop distribution | Installable shell reusing the web UI and launching the API plus Recoll as bundled sidecars |

## Intended shape

- **One** Recoll index for all documents, not one per collection. Collection membership is per-file
  metadata supplied by the service at index time, not directory layout, so two files in the same
  directory can belong to different collections and the documents are never modified.
- A Python service owns Recoll through its native Python bindings (`from recoll import recoll`).
- SQLite holds collections, membership, indexing jobs, users and sessions.
- An HTTP API consumed by both the web UI and the MCP server, so the two never diverge.
- A Docker image containing Recoll itself, plus compose wiring for document volumes and index storage.
- A packaging seam for a future desktop shell: application logic does not depend on Docker, state paths
  and listen addresses are configurable, process startup/shutdown is explicit, and every UI operation
  crosses the same HTTP API. Docker remains the only supported distribution through spec 004.

### Component boundaries

| Module | Responsibility |
|---|---|
| `api/` | HTTP transport, validation, auth dependencies and serialization |
| `domain/` | Framework-independent collection, document, membership, rule and job behavior |
| `storage/` | SQLite migrations, transactions and repositories |
| `indexing/` | Discovery, hashing, directory-rule reconciliation, map export and queue worker |
| `engine/` | The search/index Protocol, fake implementation and Recoll adapter |
| `app.py` | Configuration, dependency wiring and lifecycle |

Only `engine/` may import Recoll or invoke `recollindex`. Membership jobs first establish desired
state in SQLite, atomically export the helper's `RCM1` flat map, then ask the engine to force-index
affected canonical paths. Map records use length-prefixed absolute UTF-8 paths, so filenames can
contain newlines. The C helper reads this private map without starting Python. Engine retries are
therefore idempotent. Jobs save paths needed for replay before changing rule membership, and collection
deletion commits the cleanup job in the same SQLite transaction. Persistent directory rules reconcile
at startup and on an explicit reindex, preserving prior membership for unreadable files or subtrees,
not through live filesystem monitoring.

### Storage model

`collections`, `documents` and `document_paths` hold identity and canonical paths. Membership provenance
is normalized: `direct_memberships` holds explicit files and snapshot expansions; `directory_rules`,
`directory_rule_exclusions` and `rule_memberships` hold persistent additions; and
`membership_exclusions` holds per-file overrides against rule-derived membership. Effective membership
is direct membership union non-excluded rule membership, so direct additions remain additive.

`jobs` and `job_file_errors` make work and partial failures durable. At startup, the worker requeues
well-formed interrupted jobs, clears errors from the prior attempt, and fails unreadable requests.
`users` and hashed-token `sessions` provide authentication; the session lifetime is configurable and
defaults to 12 hours. `schema_migrations` is forward-only. The exact columns and constraints are the
contract in `docs/specs/001-search-engine-api.md`.

### HTTP boundary

The app lifespan creates state, migrates SQLite, seeds the first administrator, exports the initial
membership map, recovers interrupted jobs, reconciles persistent rules, and starts/stops one worker.
Core routes use a server-side session cookie and CSRF token; `GET /auth/session` rotates the token so
the database only stores hashes. Forwarded scheme, host and prefix are applied only for configured
proxy networks.

Membership, rule, and reindex writes create versioned, durable jobs. The worker updates SQLite
provenance, exports the membership map, and forces affected paths through the engine. Document listing
derives effective membership from SQLite and includes direct and rule provenance.
An unfiltered reindex always includes the document root, even when rule reconciliation also changed
individual paths. Observing an earlier duplicate forces both the new and former canonical paths
through Recoll so only the canonical copy carries collection tags. Resubmitting a persistent rule in
best-effort mode retains prior members under discovery-error paths, as normal reconciliation does.

Search passes all requested collection IDs into one engine query, then verifies hit paths and effective
membership in SQLite before returning them. Full-text and original-file routes resolve a live canonical
path under the configured root. Original downloads open a contained regular file through no-follow
directory descriptors and stream from the pinned descriptor, including single byte ranges; inline
display is limited to safe media types.

The image installs Debian trixie's headless `recollcmd` package and Python binding.
It syncs the application into a system-site-packages venv so the binding remains
importable. A separate build stage compiles the C helper. The non-root process
copies Recoll config templates into the persistent state volume only when absent;
Recoll may generate additional support files there. Compose mounts documents
read-only and keeps the SQLite/config and Xapian index volumes separate. Initial
health can be 503 until an indexing job creates the first index.

Gitea Actions tests and builds on pull requests, main pushes and version tags. A dependent job publishes
`linux/amd64` images only for main and full `vX.Y.Z` tags. `main` follows the branch; `latest` follows
the newest pushed version tag. The job uses package-write repository Actions secrets. The local
Compose deployment builds from source; `compose.published.yaml` pulls the registry image with the same
runtime mounts.

The host Recoll contract tests skip when no container is running. Required-container mode executes the
adapter inside Compose, avoiding a host Recoll dependency; the generated-corpus test proves that a
read-only file can be indexed, searched in two collections, and retrieved as extracted text. The HTTP
lifecycle test uses a deterministic engine to exercise rules, identity, projection, canonical-path
promotion and interrupted-job recovery.

The resource groups are auth, health, read-only file browsing, collections and membership sources,
directory rules, scoped search, document text/original retrieval, and indexing jobs. Search callers
select returned fields; only `document_id` is unconditional, and inline full text is bounded. Every
route, cookie, redirect, OpenAPI URL and generated link supports a configured mount prefix. Forwarded
prefix and origin data are used only from trusted proxies. The exact endpoints and error codes are the
contract in `docs/specs/001-search-engine-api.md`.
The built-in OpenAPI JSON and documentation pages also require a valid session, including the Swagger
OAuth redirect route; prefix middleware applies that guard after normalizing the mount path.

## Verified Recoll mechanics

Established empirically on 2026-09-18 in a throwaway `debian:trixie-slim` container running
Recoll 1.43.0 / Xapian 1.4.29, with the document tree bind-mounted **read-only**. Re-verify if the
Recoll major version changes.

- **Documents are never written to.** Membership reaches the index through `metadatacmds` in
  `recoll.conf` (`metadatacmds = ; collection = <helper> %f`), which Recoll runs per file at index time
  to fetch external metadata. The helper answers from our own store. Indexing a read-only mount
  succeeds; `touch` and `setfattr` on it both fail, as they must.
- **Extended attributes are NOT usable.** An earlier design carried membership in a `user.collection`
  xattr. It works only when the documents are writable, so it is superseded — see `docs/DECISIONS.md`.
- **Multi-membership works.** A space-separated helper response puts one file in several collections.
  An `OR` across collections returns it **once**, in a single coherently ranked set: Xapian does the
  ranking, so no application-side merging is needed.
- **Membership changes need a forced per-file reindex.** Neither a plain incremental run nor
  `recollindex -i <file>` notices a change that did not touch the file — Recoll's change signature is
  size + mtime (observed as `sig` = `'<size><mtime>'`), and a membership change alters neither.
  `recollindex -i -Z <file>` does pick it up, at roughly 15ms per file, and accepts several paths.
- **The field value is tokenised and matched case-insensitively.** A value of `cook-books` is matched by
  `collection:cook` *and* `collection:books`; `TechBooks` by `collection:techbooks`. Collection
  identifiers must therefore be opaque single tokens with no separators. Tested clean with `^c[0-9a-f]+$`.
- **Recoll has no content hash.** `md5` is empty and `sig` is only size + mtime, so document identity by
  content is ours to compute and store.
- **An unscoped query returns every document**, including ones belonging to no collection. Recoll will
  not enforce collection scoping; the API layer must.
- **The helper must start fast.** Recoll spawns it once per file per index run. Over 400 files: 0.09s
  with no helper, 0.13s for a shell+awk helper, 0.82s for a `python3` helper — interpreter startup
  dominates. The helper reads a flat map file exported from SQLite; it is not a Python process.

## Open design questions

Closed by the 001 brainstorm (2026-09-18) — see `docs/DECISIONS.md` for the reasoning:

1. ~~Collection isolation~~ — one index; membership is an opaque collection ID supplied to Recoll by
   `metadatacmds` at index time; human names live only in SQLite; documents are never written to.
2. ~~Cross-collection search~~ — allowed, but only when explicitly requested. Ranking is Xapian's.
3. ~~Indexing trigger~~ — an in-process job queue, backed by SQLite.
4. ~~Stack~~ — Python + FastAPI, managed with `uv`.
5. ~~Auth and exposure~~ — real authentication in 001; user administration deferred to 004.
6. ~~Result presentation~~ — callers select result fields; metadata plus snippets is the default, inline
   text is bounded, and full text and file download are separate endpoints.

The remaining 001 design questions — component boundaries, schema, HTTP surface, pagination, error
semantics and test strategy — are closed in the approved `docs/specs/001-search-engine-api.md`.

## External dependencies

| Dependency | What breaks without it |
|---|---|
| Recoll (in-container) | All indexing and search. Not installed on the host — see `AGENTS.md` Rules. |
| Docker + compose | The only supported way to run the service. |
| Document volumes | Nothing to index; collections resolve to empty. |
| A writable volume for the index and SQLite | All state. The document volume itself may be mounted read-only. |

Docker is the only supported deployment for specs 001–004, not a permanent application-layer
dependency. Spec 005 will design cross-platform packaging of the web UI, API service, Recoll and its
document filters. A Tauri-style shell with bundled sidecars is the intended approach; choosing Tauri
itself and resolving per-platform Recoll licensing, signing, updates and filter coverage are decisions
for that spec.

## Invariants

- A query never silently spans collections: the scope is an explicit, required parameter, and the API
  refuses a search that does not name one.
- Collection identity in the index is an opaque single-token ID, never a user-supplied name, so
  collections cannot bleed into one another and renaming never touches the index.
- The service never writes to the documents it indexes. The document volume is treated as read-only
  even when it is not, and the deployment mounts it `:ro`.
- Document identity is the SHA-256 of file content, not its path or name: two files with the same name
  and different content are two documents, and one file reachable by several paths is one document.
- Indexed content is never written into the repository.

## Known rough edges

See the deferred investigations and known issues in `docs/TODO.md`.
