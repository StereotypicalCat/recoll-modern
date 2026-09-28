# Decisions

Append-only, newest first. Never edit or delete an entry — supersede it with a new one that links back.
One entry per decision a future maintainer would otherwise have to reverse-engineer.

## 2026-09-28 — Default registry login to the triggering Gitea account
**Status:** accepted
**Context:** The first publish run received `REGISTRY_TOKEN` but no `REGISTRY_USERNAME`, so Docker
login stopped with `username is empty`. A working Gitea workflow uses `gitea.actor` for that login.
**Decision:** default the registry username to Gitea's GitHub-compatible `github.actor` context; an
explicit `REGISTRY_USERNAME` secret overrides it when the token belongs to another account.
**Alternatives:** require a second secret for the common case (caused the first-run failure); always
use the repository owner (wrong for a token owned by a collaborating account).
**Consequences:** one package-write PAT is enough when its owner triggers the push. Other token owners
must supply the optional username secret.

---

## 2026-09-28 — Isolate registry credentials and tag the built image ID
**Status:** accepted
**Context:** A persistent Gitea runner can retain Docker login credentials, and jobs sharing a Docker
daemon can overwrite a common local image tag while publishing concurrently.
**Decision:** the publish script uses a fresh temporary Docker config, removes it on exit, and tags the
immutable ID returned by its own build. Document isolated runner jobs as a deployment prerequisite.
**Alternatives:** log in to the runner's default Docker config (credential residue); tag a shared local
name (revision race); serialize all image jobs (unnecessary when each job tags its own image ID).
**Consequences:** routine success and failure paths remove the PAT, and overlapping jobs do not reuse
each other's local image tag. Runner isolation still matters for abrupt host failures and untrusted jobs.

---

## 2026-09-28 — Publish one amd64 image through Gitea Actions
**Status:** accepted
**Context:** The Docker deployment exists, but operators must build it locally. [Gitea's documented job
token limitation](https://docs.gitea.com/usage/actions/comparison/) means the workflow needs separate
package credentials.
**Decision:** run checks and build on pull requests, main and version tags. After checks, publish
`gitea.lucaswinther.info/lucasw89/recoll-modern:main` for main and `:vX.Y.Z` plus `:latest` for a full
version tag. Use a package-write personal access token stored as repository Actions secrets. The first
published architecture is `linux/amd64`; the existing local build remains available.
**Alternatives:** tag every main commit as `latest` (makes releases ambiguous); use Buildx for multiple
architectures now (requires more runner setup); use `GITEA_TOKEN` (currently lacks package publishing).
**Consequences:** operators can pin a version, while `main` is a development image. Publishing requires
a Docker-capable Gitea runner and configured secrets; no external deploy occurs automatically.

---

## 2026-09-28 — Reject non-regular explicit sources before opening
**Status:** accepted
**Context:** Directory discovery filters non-regular entries, but an explicit file source could name
a FIFO. Opening that path for hashing blocks while waiting for a writer.
**Decision:** open explicit sources with `O_NONBLOCK` and `O_NOFOLLOW`, inspect the opened descriptor's
file mode, and return `file_hash_failed` for non-regular sources. Retain the existing before/after
metadata checks for content changes.
**Alternatives:** rely on directory discovery alone (explicit sources bypass it); open every path first
(can block on a FIFO).
**Consequences:** an explicit FIFO, including one swapped into place immediately before opening,
is reported as a file error without blocking the worker.

---

## 2026-09-28 — Keep exception dataclasses mutable for transaction propagation
**Status:** accepted
**Context:** Python's generator-based context managers assign `__traceback__` while re-raising an
exception. Frozen `AppError` and `PathPolicyError` dataclasses rejected that assignment, replacing an
expected application error with `TypeError` when it crossed `Database.transaction()`.
**Decision:** retain `slots=True` but remove `frozen=True` from both exception classes.
**Alternatives:** move all error checks outside transactions (introduces races); wrap every exception
at each transaction boundary (duplicates handling and can change error identity).
**Consequences:** the original application or path error survives rollback and reaches its caller.
The transaction regression test covers both exception types.

---

## 2026-09-28 — Guard generated API documentation with the service session
**Status:** accepted
**Context:** FastAPI exposes generated OpenAPI and documentation routes outside ordinary route
dependencies. The accepted spec requires authentication for every route except health and login while
also requiring OpenAPI to work under a configured mount prefix.
**Decision:** enforce the existing session check on the generated routes in prefix middleware after
path normalization. Keep OpenAPI and the documentation pages available to logged-in clients.
**Alternatives:** leave documentation public (violates R24); disable it (violates the intended OpenAPI
surface under R29); add a separate authentication mechanism for documentation (unnecessary state).
**Consequences:** generated documentation shares the API's cookie authentication and URL prefix.

---

## 2026-09-27 — Persist replay paths and pin original downloads
**Status:** accepted
**Context:** Review found that a job could mutate rule or collection state before its indexing step
failed, leaving a retry without the old paths. `FileResponse` also reopened a path after containment
checking, allowing a concurrent host-side symlink swap.
**Decision:** persist affected paths in a running job before rule mutations; enqueue collection cleanup
atomically with collection deletion. Open original files beneath the document root with no-follow
directory descriptors and stream from that checked descriptor, including byte-range responses.
**Alternatives:** recompute old paths on retry (the database may already have lost them); retain
`FileResponse` after a path-only check (it reopens the path).
**Consequences:** interrupted jobs retain their required reindex paths. File responses are tied to an
opened regular file even if directory entries change later. The descriptor traversal relies on Linux
`openat` semantics supplied by the current Docker deployment; desktop packaging must revisit it.

---

## 2026-09-18 — Cross-platform desktop packaging is spec 005
**Status:** accepted
**Supersedes:** "The product is four specs, built in order" (below, same date), only by appending a fifth
delivery after 004; the original order and boundaries of specs 001–004 remain unchanged.
**Context:** the hosted Docker service should eventually also be usable as a self-contained installable
application on Linux, macOS and Windows, without distracting from delivery of the core product.
**Decision:** desktop distribution is spec 005 and starts only after 004. Its intended architecture is a
Tauri-style shell that reuses the web UI and launches the existing HTTP API plus Recoll as bundled local
sidecars. Tauri is the leading candidate, not a selected dependency; that choice belongs to 005.
**Alternatives:** call backend libraries directly from a native shell (creates a second integration
path); hide Docker behind a launcher (still requires a container runtime and integrates poorly with the
desktop filesystem).
**Consequences:** specs 001–004 stay Docker-first, but application logic cannot depend on Docker. State
paths and listen addresses are configurable, lifecycle is explicit, and UI behavior crosses the HTTP
API. Spec 005 must resolve per-platform Recoll packaging and licensing, filters, loopback security,
signing, updates and installer formats before adding dependencies.

---

## 2026-09-18 — Deployment supports a configured URL subpath
**Status:** accepted
**Context:** the service may sit behind an existing reverse proxy under a path such as `/recoll`, not at
the origin root. Hard-coded root URLs break redirects, cookies, OpenAPI and document links there.
**Decision:** one configured external mount prefix drives routing, generated URLs and cookie scope.
Forwarded scheme, host and prefix values are honored only from explicitly trusted proxies.
**Alternatives:** root-only hosting (needlessly constrains deployment); trust every forwarded header
(lets a direct client forge external URLs and cookie paths).
**Consequences:** API and end-to-end tests run at both `/` and a non-root prefix. Proxy configuration is
part of deployment documentation, and all URL generation goes through one boundary.

---

## 2026-09-18 — Search result fields are caller-selected
**Status:** accepted
**Supersedes:** the fixed result shape in "Search results carry metadata and snippets, not full text"
(below, same date). The metadata-plus-snippets shape remains the default, not the only representation.
**Context:** browser and MCP consumers have different response-size needs, and users need to choose
whether results include metadata, snippets, extracted text or retrieval links.
**Decision:** `document_id` is unconditional; callers select all other result fields. Inline extracted
text is opt-in, bounded and marked when truncated. Authenticated endpoints return full extracted text
and stream the canonical original separately.
**Alternatives:** one fixed rich shape (wastes bandwidth and agent context); metadata-only search with a
follow-up per hit (too many round trips); unbounded full text inline (a book can dominate the response).
**Consequences:** field projection is part of the engine/API contract. Generated retrieval links honor
the configured mount prefix, and original-file responses require range and safe-disposition handling.

---

## 2026-09-18 — Directory membership has normalized additive provenance
**Status:** accepted
**Context:** users need both one-time directory expansion and persistent directory membership, including
the ability to omit metadata subdirectories such as `.calibre`. Overlapping sources must not make
removal order-dependent.
**Decision:** direct file additions and snapshot expansions are durable direct membership. Persistent
directory rules materialize their own contributed documents and hold exact recursive exclusions scoped
to the rule. Per-file removal creates an override against rule-derived membership; an explicit direct
addition still wins. Persistent rules reconcile at startup and explicit reindex, not through watching.
**Alternatives:** one polymorphic source ledger (weaker relational constraints); recompute every rule on
demand (slow and nondeterministic); persistent rules without provenance (removing one rule can erase
membership contributed by another).
**Consequences:** the schema has separate direct, rule-derived and exclusion tables. Directory symlinks
are never followed; file symlinks are accepted only inside the document root. Jobs default to
best-effort, while strict jobs scan first and apply no membership changes if any file fails.

---

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

---

## 2026-09-26 — Retrieve text by Recoll UDI and expose rank-based score
**Status:** provisional until the real-container contract runs
**Context:** the approved plan proposed an escaped path query for complete text and a relevance score.
Recoll's Python API documents `fsudi.fs_udi(path)` and `Db.getDoc()` for exact path lookup, but does not
document a numeric query weight on returned documents.
**Decision:** derive the UDI from the canonical path for full-text extraction. Set `score` to the
reciprocal result rank, preserving Recoll's order across pages while making no claim that the number
is Xapian's raw weight.
**Alternatives:** a query-language path clause that must safely encode quotes and parentheses; an
undocumented Recoll binding attribute for score.
**Consequences:** unusual filenames do not enter a query parser. Clients can compare score order within
one query, but the value is a rank proxy. Revisit this once the real Recoll container can be tested.

---

## 2026-09-26 — Rotate CSRF tokens on session reads
**Status:** accepted
**Context:** sessions store only SHA-256 token digests, but `GET /auth/session` must return a usable CSRF
token after a page reload. The raw token cannot be recovered from SQLite.
**Decision:** authenticate the session, replace its stored CSRF digest, and return a newly generated
token. The previous token becomes invalid immediately.
**Alternatives:** store the raw CSRF token; derive a repeatable token from the cookie and a server key.
**Consequences:** clients should refresh their CSRF token after calling the session endpoint. Session
storage contains no raw cookie or CSRF token.

---

## 2026-09-26 — Persist writable Recoll config beside service state
**Status:** accepted
**Context:** Debian Recoll 1.43 writes generated support files into its config directory. A non-root
container cannot write to image-owned `/etc/recoll-modern`; a live first-boot test surfaced this.
**Decision:** keep immutable templates under `/etc/recoll-modern`, copy each missing template into
`/var/lib/recoll-modern/recoll-config` on startup, and point both the engine and indexer there. Never
overwrite an existing runtime config file. Keep the Recoll index in its own named volume.
**Alternatives:** chown `/etc/recoll-modern` in the image (runtime changes would not survive container
replacement); run the service as root.
**Consequences:** service-state backups include generated Recoll configuration, and config changes made
by an operator persist across image upgrades. Template updates require an explicit migration if an
existing config should adopt them.

---

## 2026-09-26 — Treat an empty Recoll document URL as a missing hit
**Status:** accepted
**Context:** the live Recoll 1.43 Python binding returns a `Doc` object with an empty `getbinurl()` for
a UDI absent from the index; it does not return `None`. Passing that object to `rclextract.Extractor`
raises an internal-file error.
**Decision:** check the returned URL before extraction and return empty text for an absent UDI.
**Alternatives:** catch the generic extraction error, which would hide genuine extraction failures.
**Consequences:** exact-path text lookup follows the engine contract for missing documents while real
extraction failures still surface as `engine_unavailable`.
