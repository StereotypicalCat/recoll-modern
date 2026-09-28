---
status: approved
plan: docs/plans/006-gitea-image-publishing.md
supersedes: none
---

# 006 — Gitea image publishing

## Why

Operators currently have to clone the repository and build the Docker image themselves. Publish the
already supported Docker deployment to the project's Gitea container registry so an operator can pull
a known image and start the service with persistent state and read-only documents.

## Scope

**In:** Gitea Actions checks and image publishing; image naming, tagging and metadata; a deployment
example using the published image; README instructions for registry access, pulling, startup and
persistent volumes.

**Out:** automatic deployment to a server; changing the application stack, HTTP API or authentication;
deleting or rebuilding an index; image signing; multiple CPU architectures in this first release.

## Requirements

- **R1.** Gitea Actions runs tests, lint, type checking and a Docker image build for proposed changes,
  pushes to `main` and version tags. A failed check prevents the corresponding publishing job from
  running.
- **R2.** The image is published to
  `gitea.lucaswinther.info/lucasw89/recoll-modern` for `linux/amd64` only. A push to `main`
  publishes the mutable `main` tag. A pushed semantic version tag of the form `vX.Y.Z` publishes
  that version tag and the mutable `latest` tag. Pull requests never publish.
- **R3.** The publishing job authenticates with a repository secret holding a Gitea personal access
  token with package write access. The token is scoped to that job, and instructions explain how to
  create and set the required username and secret. No credential is committed or printed.
- **R4.** The published image includes OCI metadata identifying the source repository, description,
  revision and version or ref, so its provenance is inspectable with Docker.
- **R5.** A published-image Compose example uses the same port, administrator seed, document mount,
  state volume, index volume, health check and restart behavior as the local-build deployment. It
  pulls a selectable image tag and does not require source code or a local build.
- **R6.** The README gives copyable commands to authenticate when necessary, pull and start a
  published image, inspect its status, and preserve data during updates. It explains the `main`,
  `latest` and version-tag meanings, the `linux/amd64` limit, first-boot index readiness, and the
  difference between documents, service state and index storage.
- **R7.** The local-build Compose workflow remains available. Publishing changes no application
  runtime behavior, schema, public API, document data or Recoll index contents.

## Acceptance

1. The workflow file passes a local syntax/structure check, and the complete project checks and
   Docker build pass in this session.
2. A published-image Compose configuration validates without invoking a build and references the
   intended registry image and persistent mounts.
3. README commands can be followed with only Docker, registry credentials when required, a document
   directory and administrator seed credentials.
4. A real publish and pull is verified in Gitea after the branch is merged and the required runner
   and package-write secret are configured. This cannot be claimed from local checks alone.
