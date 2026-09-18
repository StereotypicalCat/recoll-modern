# TODO

Durable backlog. Agents append here instead of leaving `TODO` comments in source.
Small, specific, independently actionable. Remove only when actually done.

## Now
- [ ] Answer the open questions in the bootstrap report, then fill the `Commands` section of `AGENTS.md`
      and delete its `TODO(maintainer)` line.
- [ ] Brainstorm -> spec `docs/specs/001-*.md` covering the open design questions in
      `docs/ARCHITECTURE.md`, starting with collection isolation and the stack choice.

## Next
- [ ] Scaffold the chosen stack; verify install/dev/test/lint/typecheck/build commands by running them,
      then record the verified ones in `AGENTS.md`.
- [ ] Dockerfile + compose: Recoll in the image, volumes for documents and indexes.
- [ ] Write `PRODUCT.md` properly via `/impeccable init` — the current file is a stub from the initial
      brief, not an interview.

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
