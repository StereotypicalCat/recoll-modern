# Decisions

Append-only, newest first. Never edit or delete an entry — supersede it with a new one that links back.
One entry per decision a future maintainer would otherwise have to reverse-engineer.

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
