# Product

<!-- impeccable:product-schema 1 -->

> **Stub, not an interview.** Every fact below is taken verbatim from the project brief that opened this
> repository, or marked as undecided. Nothing here was confirmed in an `/impeccable init` interview.
> Run `/impeccable init` before the first UI work and let it replace this file.

## Platform

web

## Stack

The backend stack was confirmed during the 001 design: Python + FastAPI, managed with `uv`, because
Recoll provides native Python bindings. The frontend stack remains undecided. No application has been
scaffolded yet. See `docs/DECISIONS.md` for the decision and `AGENTS.md` for installed toolchains.

## Users

Undecided — not yet interviewed. From the brief, the product is self-hosted on a server the user
controls, which implies a technical operator running it for themselves or a small group. Confirm before
designing around it.

## Product Purpose

A layer on top of Recoll, a Linux desktop full-text search and indexing tool. It exists to give Recoll
a modern, sleek interface, to run as a hosted service rather than a desktop app, and to hold several
independent document collections at once (stated examples: `techbooks`, `cookbooks`).

## Positioning

Recoll's own interfaces are a desktop GUI and a basic bundled web UI, both single-index and
single-machine. This product's stated difference is a hosted, multi-collection service with a modern
interface and an MCP server, so the same index is usable by a person in a browser and by an AI agent.

## Operating Context

- Deployed with Docker on a server; used through a browser.
- Collections map to bodies of documents the user keeps, named by subject.
- A second consumer is an MCP client (an AI agent), searching the same collections programmatically.

## Capabilities and Constraints

Confirmed from the brief:
- Full-text search and indexing, provided by Recoll.
- Multiple named collections, managed independently.
- Web UI, served from a Docker deployment.
- MCP server exposing the same search capability.

Explicitly undecided: authentication, cross-collection search, indexing schedule, result preview depth,
supported document types beyond Recoll's own. See `docs/ARCHITECTURE.md` for the full list.

## Brand Commitments

Working name: `recoll-modern`. No logo, palette, typography, or voice has been established.
"Modern and sleek" is the only stated aesthetic constraint — recorded as-is, not expanded.

## Evidence on Hand

None. No screenshots, copy, sample collections, user research, or existing interface exist in this
repository. Future work must not fabricate any.

## Product Principles

Undecided — these are derived from a confirmed interview, which has not happened. Leaving this section
empty is deliberate; do not invent principles to fill it.
