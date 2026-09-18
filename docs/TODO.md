# TODO

Durable backlog. Agents append here instead of leaving `TODO` comments in source.
Small, specific, independently actionable. Remove only when actually done.

## Resume here

Last touched 2026-09-18. Still greenfield: **no application code exists.**

Where the workflow stands (`AGENTS.md` -> Workflow: brainstorm -> spec -> plan -> TDD -> review):

- Brainstorm for spec 001: **done.** All six design questions in `docs/ARCHITECTURE.md` are closed, with
  reasoning in `docs/DECISIONS.md`.
- Spec `docs/specs/001-search-engine-api.md`: **written, `status: draft`.** It has had its self-review
  pass but **has not been signed off by the maintainer.** Do not start a plan or write code against it
  until its front matter says `approved`.
- Plan `docs/plans/001-search-engine-api.md`: **not written.** It is the next artefact, and only after
  sign-off.

The next action is to ask the maintainer to review the spec. If they approve it, set `status: approved`
and invoke the superpowers `writing-plans` skill to produce `docs/plans/001-search-engine-api.md`,
numbered to match.

Things a resuming agent will otherwise get wrong:

- The design carried collection membership in a `user.collection` extended attribute for part of this
  session. **That is superseded** — the documents are read-only. `docs/DECISIONS.md` has both entries,
  newest first; the older one is left intact by that file's append-only rule, so read the newer one.
- The Recoll facts in `docs/ARCHITECTURE.md` -> "Verified Recoll mechanics" were measured in a container,
  not recalled. Trust them over intuition, and re-verify only if Recoll's major version moves.
- The throwaway spike container is not part of the repo and does not survive the session. Everything
  worth keeping from it is already in `docs/`.
- `uv` was installed on this host during this session and `AGENTS.md` was corrected accordingly. The
  `Commands` section of `AGENTS.md` is still a `TODO(maintainer)` stub and must be filled in the same
  commit that scaffolds the app, with every command actually run first.

## Now
- [x] Answer the six open design questions in `docs/ARCHITECTURE.md` — closed 2026-09-18, reasoning in
      `docs/DECISIONS.md`.
- [ ] Finish the 001 design: component boundaries and SQLite schema, API surface and error semantics,
      test strategy. Then write `docs/specs/001-search-engine-api.md`.
- [ ] Fill the `Commands` section of `AGENTS.md` and delete its `TODO(maintainer)` line — must happen in
      the same commit that scaffolds the app, with every command actually run.

## Next
- [ ] Scaffold Python + FastAPI with `uv`; verify install/dev/test/lint/typecheck/build by running them,
      then record the verified ones in `AGENTS.md`.
- [ ] Dockerfile + compose: Recoll in the image, document volume mounted `:ro`, writable volumes for
      the index and SQLite.
- [ ] Write the `metadatacmds` membership helper as a fast-starting non-Python program, fed by a flat
      map exported from SQLite. A `python3` helper made a 400-file index 9x slower; Recoll spawns it
      once per file per index run.
- [ ] Re-measure indexing overhead against real documents (PDF, EPUB) rather than small text files —
      extraction cost should dwarf the helper, but that is an assumption until measured.
- [ ] Promote a new canonical path and force a reindex when a canonical path disappears, or the
      document silently leaves every collection it is in.
- [ ] Recover interrupted indexing jobs at startup; they do not survive a process restart on their own.
- [ ] Write `PRODUCT.md` properly via `/impeccable init` — the current file is a stub from the initial
      brief, not an interview. Blocks spec 002.

## Someday
- [ ] Propose a CI check (Gitea Actions): assert `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and the `docs/`
      paths exist, and fail if `AGENTS.md` exceeds 150 lines.

## Known issues
- None recorded yet.

## Recurring
- [ ] Add an `AGENTS.md` rule only in response to a real, observed agent failure — one line, ideally with
      a code example. Never pre-empt hypothetical mistakes.
- [ ] Update `AGENTS.md` in the same commit as the convention it describes. A stale rules file misleads.
- [ ] Prune quarterly: delete rules whose convention changed or whose mistake no longer occurs.
