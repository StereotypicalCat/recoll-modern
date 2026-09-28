# TODO

Open work only. Record completed work in its spec, plan, commits, and `docs/DECISIONS.md`; do not
leave `TODO` comments in source.

Spec 001 is implemented on `main`. The next product step is spec 002 (web UI). Its first step is the
`/impeccable init` interview to replace the `PRODUCT.md` stub; the first UI build then creates
`DESIGN.md`. Follow the spec → plan → TDD → review workflow in `AGENTS.md`.

## Product and engineering backlog

- [ ] Verify a `vX.Y.Z` push publishes both its version tag and `latest` during the next planned
      release, then mark spec 006 implemented. The `main` image was published and pulled successfully
      after commit `6110818`.
- [ ] Decide whether a persistent directory rule may target the document root. Current sources require
      a named child directory.
- [ ] Investigate whether Recoll's Python binding exposes a native numeric relevance score. The API
      currently returns a rank-based proxy; exact-path text retrieval was verified in the container.
- [ ] Measure membership-helper indexing overhead on representative PDF and EPUB documents. Current
      measurements cover small text files only.
- [ ] After spec 004, design spec 005 for an installable desktop distribution, including framework,
      Recoll packaging and licensing, signing, updates, and filter coverage.
- [ ] Consider a Gitea Actions check for required agent/docs files and the `AGENTS.md` length limit.

## Known issues

- The API tests report deprecation warnings from FastAPI/Starlette's TestClient dependencies. Update
  the client integration when a supported replacement is available.
- The repository ID test checks the collection ID prefix and length, rather than the full
  `^c[0-9a-f]{10}$` pattern. The implementation uses `secrets.token_hex(5)`; strengthen this
  regression assertion when touching that test.
