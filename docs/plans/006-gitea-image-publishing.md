---
status: draft
spec: docs/specs/006-gitea-image-publishing.md
---

# Gitea Image Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the existing Docker service to Gitea with predictable tags and give operators a pull-based deployment recipe.

**Architecture:** A small tag script validates Git refs and gives the workflow exact OCI tags. One Gitea Actions workflow runs the project gates and Docker build, then publishes only trusted main and release events with a package-write PAT. A second Compose file is the source-free deployment entry point; README and architecture docs explain it.

**Tech Stack:** Python 3.13, uv, Docker/Compose, Gitea Actions, Gitea Container Registry.

**Spec:** `docs/specs/006-gitea-image-publishing.md`

## Global Constraints

- Registry image: `gitea.lucaswinther.info/lucasw89/recoll-modern`.
- `main` publishes `:main`; `vX.Y.Z` publishes that version and `:latest`; pull requests never publish.
- Initial image platform: `linux/amd64` only.
- No new runtime dependencies, API/schema/auth changes, or changes to indexed documents or Recoll data.
- CI credentials come only from `REGISTRY_USERNAME` and `REGISTRY_TOKEN` repository secrets; `REGISTRY_TOKEN` needs Gitea package write permission.
- Existing `compose.yaml` remains the local-build path; `compose.published.yaml` is pull-only.

## Review Focus

- A `v1.2.3-rc1` or arbitrary `vfoo` ref must not publish as a release.
- A pull request ref must produce no publishable tags, even if its branch name resembles a release.
- Registry secrets must be absent from pull request jobs and never appear in command output.
- A fresh published deployment must keep `/documents` read-only and use separate persistent state and index volumes.
- An operator choosing a fixed version tag must not accidentally use mutable `latest` on the next update.

---

### Task 1: Tag policy

**Files:**
- Create: `scripts/image_tags.py`
- Create: `tests/test_image_tags.py`

**Interfaces:**
- `tags_for_ref(ref: str) -> list[str]`: returns the tag suffixes for a `refs/heads/main` or `refs/tags/vX.Y.Z` ref; returns an empty list otherwise.
- CLI receives a ref and writes newline-separated full image references to stdout. The workflow consumes these references. Invalid refs return no tags, not a guessed tag.

- [ ] **Step 1: Write failing tests** for main (`["main"]`), `v1.2.3` (`["v1.2.3", "latest"]`), prerelease/malformed versions, branch names containing `main`, and pull request refs (empty results). Assert CLI output uses the exact registry image.
- [ ] **Step 2: Run** `uv run pytest tests/test_image_tags.py -v`; confirm the new tests fail because the module is absent.
- [ ] **Step 3: Implement** `tags_for_ref` and the CLI in `scripts/image_tags.py` with an anchored `v[0-9]+\.[0-9]+\.[0-9]+` release match.
- [ ] **Step 4: Run** `uv run pytest tests/test_image_tags.py -v` and `uv run ruff check scripts tests/test_image_tags.py`; confirm both pass.
- [ ] **Step 5: Commit** the script, tests and checked plan boxes as `feat: define published image tags`.

### Task 2: Gitea checks and publishing

**Files:**
- Create: `.gitea/workflows/image.yaml`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DECISIONS.md`

**Interfaces:**
- Consumes `python scripts/image_tags.py "$GITHUB_REF"` from Task 1.
- Produces `:main` on main, and `:vX.Y.Z` plus `:latest` on a full release tag after all gates pass.
- Requires a Docker-capable Gitea runner with `ubuntu-latest` label and Gitea Actions secrets `REGISTRY_USERNAME` and `REGISTRY_TOKEN` for the publish job.

- [ ] **Step 1: Run a failing structure check** (`test -f .gitea/workflows/image.yaml`) and record that no workflow exists.
- [ ] **Step 2: Add** one workflow triggered by pull requests, main pushes and `v*` tag pushes. Use `actions/checkout`, `astral-sh/setup-uv`, `uv sync --locked`, `uv run pytest`, `uv run ruff check .`, `uv run mypy src tests`, and `docker build --platform linux/amd64`. Publishing is a separate job after checks, gated to main or validated release tags; log in through `docker login --password-stdin`, then tag and push each output of Task 1's script. Grant the built-in token read-only repository access; expose PAT secrets only in the publishing job. Add OCI labels for source, description, revision and ref/version.
- [ ] **Step 3: Validate** workflow syntax with `docker run --rm -v "$PWD":/repo --workdir /repo rhysd/actionlint:1.7.12 .gitea/workflows/image.yaml`, inspect that no pull request path reaches login/push, then run project tests, lint, type checking and `docker build --platform linux/amd64 -t recoll-modern:ci .` locally. If the validator or Docker daemon is unavailable, record the exact unverified gate rather than claiming success.
- [ ] **Step 4: Document** the new delivery boundary in `docs/ARCHITECTURE.md` and the tag/PAT/platform choice in an append-only `docs/DECISIONS.md` entry.
- [ ] **Step 5: Commit** workflow, docs and checked plan boxes as `ci: publish Gitea container image`.

### Task 3: Pull-based deployment and operator guide

**Files:**
- Create: `compose.published.yaml`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/plans/006-gitea-image-publishing.md`

**Interfaces:**
- `RECOLL_MODERN_IMAGE` selects a complete image reference; default is `gitea.lucaswinther.info/lucasw89/recoll-modern:latest`.
- Other environment inputs and volume paths match `compose.yaml`.

- [ ] **Step 1: Run** `docker compose -f compose.published.yaml config` with example document/admin environment values; confirm failure because the file does not exist.
- [ ] **Step 2: Add** a pull-only Compose file that preserves the local file's port, environment, read-only document mount, `service-state` and `recoll-index` volumes, health check and restart policy. Do not include a `build:` key.
- [ ] **Step 3: Run** `docker compose -f compose.published.yaml config --format json` with example inputs. Inspect the resolved image, document `read_only` bind and both named volumes; confirm no build configuration.
- [ ] **Step 4: Update** README with a quick-start using `docker login` when needed, `RECOLL_MODERN_IMAGE`, `docker compose ... pull`, `up -d`, `ps`, `logs`, and an update that retains volumes. Explain first boot, tag semantics, `linux/amd64`, backups, Gitea Actions enablement, runner and PAT secret setup. Keep local-build instructions and revise architecture for the two deployment paths.
- [ ] **Step 5: Run** all project tests, lint and type checking again; verify Compose config for both files and `git diff --check`; inspect the whole diff against spec 006.
- [ ] **Step 6: Mark** the plan done and spec implemented only after completed local gates, then commit deployment docs/config and checked plan boxes as `docs: explain pulling and running published image`. A real Gitea publish/pull remains an external acceptance step until a runner and secret are configured and the branch is merged.
