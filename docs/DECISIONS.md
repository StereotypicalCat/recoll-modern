# Decisions

Append-only, newest first. Never edit or delete an entry — supersede it with a new one that links back.
One entry per decision a future maintainer would otherwise have to reverse-engineer.

## 2026-09-18 — Document identity is a content hash, not a path
**Status:** accepted
**Context:** the document set may contain files that share a name but differ in content, and files that
differ in name but are byte-identical. Keying membership on path merges neither and distinguishes
neither correctly.
**Decision:** a document is identified by the SHA-256 of its bytes. `documents` is keyed by that hash,
`document_paths` maps many paths to one document, and membership attaches to the document. Each document
has one **canonical path**, and only that path is reported to Recoll as belonging to any collection.
**Alternatives:** path as identity (byte-identical copies appear as separate hits for the same content);
relying on Recoll to deduplicate (it cannot — `md5` is empty and `sig` is only size + mtime).
**Consequences:** duplicate copies are indexed by Recoll but belong to no collection, so the required
collection scope makes them unreachable — verified: a scoped search over a tree with one duplicated file
returned it once. Deleting a canonical path must promote another path and force a reindex, or the
document silently leaves every collection.

---

## 2026-09-18 — Membership is supplied at index time; documents are never written to
**Status:** accepted
**Supersedes:** "One index; collection membership is an opaque per-file tag" (below, same date), which
carried membership in a `user.collection` extended attribute. That entry's xattr mechanism must not be
implemented.
**Context:** the service must work with **read-only** access to the documents it indexes. Writing an
xattr requires write access, so the superseded design fails outright on a `:ro` mount — verified:
`setfattr` returns "Read-only file system".
**Decision:** membership reaches Recoll through `metadatacmds` in `recoll.conf`
(`metadatacmds = ; collection = <helper> %f`), a documented Recoll facility for external metadata.
Recoll runs the helper per file at index time; the helper answers from our own store. Everything the
superseded entry established about opaque IDs, multi-membership and single-ranked-set OR queries still
holds — only the transport changes.
**Alternatives:** filtering Recoll's results against SQLite after the query (breaks paging and total
counts); one index per collection (cannot express two files in one directory belonging to different
collections); requiring a writable document volume (contradicts the requirement).
**Consequences:** SQLite becomes the *only* store of membership rather than the authoritative copy of
two, so drift between store and index is now impossible and no reconcile path is needed. Extended
attributes are no longer a deployment requirement. A membership change needs
`recollindex -i -Z <path>` — verified that neither a plain incremental run nor `recollindex -i` notices
it, because Recoll's change signature is size + mtime and a membership change touches neither.
The helper is spawned once per file per index run, so it must start fast: over 400 files, indexing took
0.09s with no helper, 0.13s with a shell+awk helper and 0.82s with a `python3` helper. The service
exports a flat map from SQLite for a small non-Python helper to read.

---

## 2026-09-18 — Search results carry metadata and snippets, not full text
**Status:** accepted
**Context:** Recoll can return metadata, keyword-in-context snippets, extracted plain text and the
original file. The response shape drives both the web UI and the MCP tool.
**Decision:** a search hit carries title, author, path, MIME type, size, date, score, its collections and
Recoll's snippets. Extracted text and file download are separate endpoints.
**Alternatives:** metadata only (a results list without context is markedly worse, and an MCP client
would fetch every candidate to judge it, costing more overall); metadata plus full extracted text
(responses become enormous for book-length PDFs and blow an agent's context window).
**Consequences:** one search call is enough for an agent to judge relevance. The UI needs a second call
to open a document, which is the right trade.

---

## 2026-09-18 — Authentication in 001, user administration in 004
**Status:** accepted
**Context:** the service needs real auth, but roles, user CRUD and per-collection permissions are a
subsystem in their own right, and `PRODUCT.md` currently describes a single technical operator.
**Decision:** 001 ships genuine authentication — argon2 password hashing, server-side sessions, an admin
account seeded from the environment at first boot, every endpoint behind an auth dependency. User
administration and permissions are deferred to spec 004.
**Alternatives:** no auth in the service, trusting a reverse proxy (a misconfigured proxy or an exposed
Docker port would leave the destructive endpoints naked); the full identity system in 001 (a large
addition to an already-grown spec, building for users who do not exist yet).
**Consequences:** 001 is safe to expose behind a proxy. 004 must extend the auth layer without
reshaping endpoints, so the auth dependency is designed as a seam from the start.

---

## 2026-09-18 — Search scope is an explicit, required parameter
**Status:** accepted
**Context:** `docs/ARCHITECTURE.md` proposed the invariant that a query never silently spans
collections. A Recoll query with no collection clause returns every document, including untagged ones.
**Decision:** every search names one or more collections; omitting the parameter is an error, not an
implicit "all". Multiple collections are OR-ed into one Xapian query so ranking stays coherent and each
hit reports which collections it belongs to.
**Alternatives:** single-collection-only searches (the UI and MCP would be built around a model they
later outgrow); a searchable-by-default flag (reintroduces the implicit scope the invariant forbids);
per-collection fan-out and application-side merging (scores from separate databases are not comparable,
so the merged order would be strictly worse than letting Xapian rank).
**Consequences:** the API layer enforces the invariant, because Recoll will not. Every search path needs
a test proving an unscoped request is rejected.

---

## 2026-09-18 — Indexing runs as an in-process job queue
**Status:** accepted
**Context:** collections are created at runtime, so something must index a collection the moment it is
created, and report progress back to the UI and to MCP clients.
**Decision:** creating a collection, changing membership, or calling the reindex endpoint enqueues a job.
A background worker in the same FastAPI process runs `recollindex` and records status, progress and
errors in SQLite. One container process, no broker.
**Alternatives:** `recollindex -m` real-time monitoring (one supervised process per collection, inotify
watch limits, and a new collection still needs a first full index from somewhere — revisit as an opt-in
mode later); cron-scheduled full runs (new collections sit empty until the next tick, and there is no
way to force a refresh).
**Consequences:** jobs die with the process, so the queue must recover interrupted runs at startup.
Job state is queryable, so "indexing, 40%" is available to every consumer.

---

## 2026-09-18 — Collections are runtime-managed through the API
**Status:** accepted
**Context:** collections could be declared in a mounted config file or managed at runtime.
**Decision:** collections are created, edited and deleted through the HTTP API, with SQLite as the store
of record. The service creates and maintains the index state on demand.
**Alternatives:** a declarative mounted `collections.yaml` (reproducible and git-friendly, but no
management UI without adding a write path later); one collection per subdirectory by convention (forces
the on-disk layout to match the collection layout, which the per-file membership requirement rules out).
**Consequences:** 001 grows a persistence layer, validation and migrations. `AGENTS.md` makes deleting
or rebuilding an index an ask-first operation, so the delete path needs an explicit guard rather than a
bare `DELETE`.

---

## 2026-09-18 — One index; collection membership is an opaque per-file tag
**Status:** accepted
**Context:** a collection cannot be "a directory", because files sharing a directory must be able to
belong to different collections. Verified in a throwaway Recoll 1.43.0 container — details and the
exact config in `docs/ARCHITECTURE.md` under "Verified Recoll mechanics".
**Decision:** index every document once into a single Recoll index. Membership is a `user.collection`
extended attribute mapped to a queryable Recoll field. The tag is an **opaque single-token ID**; the
human-readable name lives only in SQLite.
**Alternatives:** one index per collection with rule-based selection (a file in two collections is
stored and indexed twice and can be returned twice, and hand-picking files in a shared directory is
awkward); an explicit file list driving indexing (does not map onto Recoll's topdirs-walking model).
**Why opaque IDs:** Recoll tokenises the field value and matches case-insensitively, so a tag of
`cook-books` is also matched by `collection:cook` and `collection:books`, and `TechBooks` by
`collection:techbooks`. Names-as-tags would let collections silently bleed into each other — exactly
what the no-silent-spanning invariant forbids. Opaque IDs tested clean, with no partial matches.
**Consequences:** collection names need no character restrictions and renaming never touches the index.
Documents must sit on a volume supporting extended attributes, checked at startup — without it every
scoped search silently returns nothing. Retagging costs `recollindex -i <file>`, not a rebuild, because
a plain incremental run does not notice xattr-only changes.

---

## 2026-09-18 — Stack: Python + FastAPI, managed with uv
**Status:** accepted
**Context:** the stack was unchosen and is an ask-first decision. Recoll ships first-class Python
bindings; every other language must drive `recollq` as a subprocess and parse its output.
**Decision:** Python + FastAPI for the engine and HTTP API, with `uv` as the package manager. `uv`
0.12.16 was installed on this host as part of this decision, and `AGENTS.md` updated in the same commit.
**Alternatives:** TypeScript on Node/Bun or C# on ASP.NET Core (one language across UI, API and MCP, but
both make a fragile output parser load-bearing); a split Python engine behind a TypeScript API (two
runtimes and an extra hop inside one container).
**Consequences:** structured results with no parsing layer, and OpenAPI for free, which specs 002 and 003
can generate clients from. The web UI will likely be a second language; that boundary is the HTTP API.

---

## 2026-09-18 — The product is four specs, built in order
**Status:** accepted
**Context:** "a web UI and an MCP server over Recoll" is four subsystems. One spec covering all of them
would be too large to plan or review, and `PRODUCT.md` is still an uninterviewed stub, so any UI spec
written now would design against fiction.
**Decision:** 001 search engine + API, 002 web UI, 003 MCP server, 004 multi-user management. Each gets
its own spec, plan and review cycle. The table lives in `docs/ARCHITECTURE.md`.
**Alternatives:** one thin vertical slice through all four (would lock in a stack and a UI before
`PRODUCT.md` is real); engine plus MCP together (defensible, but it widens 001, which has already grown).
**Consequences:** 002 is blocked on `/impeccable init`. 001's HTTP API is the contract 002 and 003 are
both built against, so it is the piece that must be got right.

---

## 2026-09-18 — Override the superpowers artefact paths
**Status:** accepted
**Context:** superpowers 6.3.0 writes specs to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
and plans to `docs/superpowers/plans/YYYY-MM-DD-<feature>.md` (verified in the installed skill files).
That nests a second docs tree and dates artefacts that we want numbered and paired.
**Decision:** specs -> `docs/specs/NNN-slug.md`, plans -> `docs/plans/NNN-slug.md`, plan number matching
its spec number. Recorded in `AGENTS.md` so every session picks it up.
**Alternatives:** accept the defaults (two docs trees, no spec/plan pairing); symlink (fragile on Windows
and in containers).
**Consequences:** the override must be restated if `AGENTS.md` is ever trimmed; a superpowers upgrade
that changes its defaults needs this entry re-checked.

---

## 2026-09-18 — Adopt AGENTS.md as single source of truth
**Status:** accepted
**Context:** The repository was empty — no commits, no stack, no agent context. Agents had nothing
durable to read and would re-explore from scratch every session.
**Decision:** `AGENTS.md` is canonical; `CLAUDE.md` and `GEMINI.md` are thin pointers with no rules of
their own. Enforceable things live in `.claude/settings.json` and `.gitignore` rather than in prose.
**Alternatives:** per-tool rule files (drift and synchronisation debt); no rules file (measurably more
steps and tokens per task).
**Consequences:** rule changes happen in one file; the pointer files must stay thin; `AGENTS.md` is an
executable-context and prompt-injection surface, so changes to it get reviewed like CI config.

---

## 2026-09-18 — No DESIGN.md until the first UI exists
**Status:** accepted
**Context:** The `impeccable` skill reads `PRODUCT.md` and `DESIGN.md`. `PRODUCT.md` could be written
from the stated product intent; `DESIGN.md` could not — there is no UI, no tokens, no visual world.
**Decision:** write `PRODUCT.md` now; leave `DESIGN.md` absent. The first UI build produces it
(`/impeccable document` derives it from shipped code).
**Alternatives:** a placeholder `DESIGN.md` — rejected, it would assert a visual system that does not
exist and the skill would design against fiction.
**Consequences:** the first UI task must end by writing `DESIGN.md`, not skip it.
