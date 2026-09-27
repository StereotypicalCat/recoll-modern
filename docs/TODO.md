# TODO

Durable backlog. Agents append here instead of leaving `TODO` comments in source.
Small, specific, independently actionable. Remove only when actually done.

## Resume here

Last touched 2026-09-27. Spec 001 implementation is in review closure.

Where the workflow stands (`AGENTS.md` -> Workflow: brainstorm -> spec -> plan -> TDD -> review):

- Brainstorm for spec 001: **done.** All six design questions in `docs/ARCHITECTURE.md` are closed, with
  reasoning in `docs/DECISIONS.md`.
- Spec `docs/specs/001-search-engine-api.md`: **approved 2026-09-18.** It includes directory rules,
  selectable search fields, subpath hosting and the packaging seam for deferred desktop spec 005.
- Plan `docs/plans/001-search-engine-api.md`: **approved 2026-09-18.** Its listed Python runtime and
  development dependencies are approved. Execution follows the plan task by task.
- Plan Tasks 1–3 are complete and independently reviewed. Tasks 4–14 add discovery, content-hash
  identity, additive membership, durable jobs, the atomic membership map, the engine boundary,
  session authentication, the HTTP shell, membership/rule/job routes, scoped search and document
  retrieval, Docker packaging and acceptance coverage. Their checkboxes are current in the plan.
  The first code review found replay, reconciliation, and download races. A fix checkpoint is on
  `feat/001-document-discovery`; final verification and branch handoff remain.

The next action is Task 14 Step 6: run the full verification matrix, request a follow-up review of the
fixes, then hand off the branch. Do not repeat Tasks 1–14. The review fixes include idempotent rule
creation, persisted replay paths, atomic collection cleanup enqueue, unreadable-file preservation,
departed-path reindexing, directory-rule pagination, recovery request validation, and descriptor-pinned
downloads. The generated real-container lifecycle test covers these flows through Compose. Its 9-test
contract/integration suite passed with `RECOLL_MODERN_REQUIRE_DOCKER=1` on 2026-09-27; the host suite
passed with 157 passed and 4 skipped, and lint/type checking passed. The complete final matrix and
follow-up review still need to run before completion. Docker Compose may be running on
port 9124 with `RECOLL_MODERN_DOCUMENTS=/tmp/recoll-modern-corpus`; preserve its named volumes and
document data. Use `docker compose down` without `-v` when done.

Things a resuming agent will otherwise get wrong:

- The design carried collection membership in a `user.collection` extended attribute for part of this
  session. **That is superseded** — the documents are read-only. `docs/DECISIONS.md` has both entries,
  newest first; the older one is left intact by that file's append-only rule, so read the newer one.
- The Recoll facts in `docs/ARCHITECTURE.md` -> "Verified Recoll mechanics" were measured in a container,
  not recalled. Trust them over intuition, and re-verify only if Recoll's major version moves.
- The throwaway spike container is not part of the repo and does not survive the session. Everything
  worth keeping from it is already in `docs/`.
- `uv` was installed on this host during this session and `AGENTS.md` was corrected accordingly. Task 1
  replaced its command stub in the scaffold commit after running every listed command.

## Now
- [x] Answer the six open design questions in `docs/ARCHITECTURE.md` — closed 2026-09-18, reasoning in
      `docs/DECISIONS.md`.
- [x] Finish the 001 design: component boundaries and SQLite schema, API surface and error semantics,
      test strategy. Then write `docs/specs/001-search-engine-api.md`.
- [x] Fill the `Commands` section of `AGENTS.md` and delete its `TODO(maintainer)` line — must happen in
      the same commit that scaffolds the app, with every command actually run.

## Next
- [ ] Verify the Recoll adapter against a generated corpus in the Compose container, including
      exact-path text retrieval and whether the Python API exposes a native numeric relevance score.
- [x] Scaffold Python + FastAPI with `uv`; verify install/dev/test/lint/typecheck/build by running them,
      then record the verified ones in `AGENTS.md`.
- [x] Dockerfile + compose: Recoll in the image, document volume mounted `:ro`, writable volumes for
      the index and SQLite.
- [x] Write the `metadatacmds` membership helper as a fast-starting non-Python program, fed by a flat
      map exported from SQLite. A `python3` helper made a 400-file index 9x slower; Recoll spawns it
      once per file per index run.
- [ ] Re-measure indexing overhead against real documents (PDF, EPUB) rather than small text files —
      extraction cost should dwarf the helper, but that is an assumption until measured.
- [x] Promote a new canonical path and force a reindex when a canonical path disappears, or the
      document silently leaves every collection it is in.
- [x] Recover interrupted indexing jobs at startup; Task 6 requeues valid running jobs and fails
      unreadable requests.
- [ ] Write `PRODUCT.md` properly via `/impeccable init` — the current file is a stub from the initial
      brief, not an interview. Blocks spec 002.

## Someday
- [ ] After delivery 004, write spec 005 for a cross-platform installable desktop distribution. Start
      from a Tauri-style shell that reuses the web UI and bundles the API and Recoll as sidecars; decide
      the actual framework, licensing, signing, updates and per-platform filter coverage in that spec.
- [ ] Propose a CI check (Gitea Actions): assert `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and the `docs/`
      paths exist, and fail if `AGENTS.md` exceeds 150 lines.

## Known issues
- The API test suite reports deprecation warnings from the installed FastAPI/Starlette TestClient
  dependency. Replace its client integration when the dependency stack supports the successor API.
- Directory sources currently require a named child of the document root; decide whether the root
  itself should be accepted as a persistent rule before finishing membership endpoints.
- Task 3's repository ID test checks the generated collection ID prefix and length rather than asserting
  the full `^c[0-9a-f]{10}$` regex. The implementation uses `secrets.token_hex(5)` and is correct; add
  the stronger regression assertion when work resumes.

## Recurring
- [ ] Add an `AGENTS.md` rule only in response to a real, observed agent failure — one line, ideally with
      a code example. Never pre-empt hypothetical mistakes.
- [ ] Update `AGENTS.md` in the same commit as the convention it describes. A stale rules file misleads.
- [ ] Prune quarterly: delete rules whose convention changed or whose mistake no longer occurs.
