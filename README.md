# recoll-modern

A modern, self-hosted web UI and MCP server on top of [Recoll](https://www.lesbonscomptes.com/recoll/)
full-text search, with support for multiple independent collections.

Status: spec 001's authenticated search API and Docker deployment have completed acceptance and
review checks. The web UI and MCP server are later specs.

## Run with Docker

Set `RECOLL_MODERN_DOCUMENTS` to an absolute host directory containing documents and provide a first
administrator username and password:

```sh
export RECOLL_MODERN_DOCUMENTS=/srv/documents
export RECOLL_MODERN_ADMIN_USERNAME=admin
export RECOLL_MODERN_ADMIN_PASSWORD='use-a-long-unique-password'
docker compose up -d --build
```

The service listens on host port 8000 by default; set `RECOLL_MODERN_PUBLISH_PORT` to change it. The
document directory is mounted read-only. SQLite, the membership map and generated Recoll configuration
live in the `service-state` volume; the index lives in the separate `recoll-index` volume. Back up both
volumes together and keep a separate copy of the documents. `docker compose down` preserves the volumes;
never pass `-v` unless you intentionally want to delete the index and service state.

On first boot, the API is available but `/health` may return 503 until a membership or reindex job has
built the first Recoll index. Log in through `POST /auth/login`, create a collection, then add file or
directory sources through `POST /collections/{id}/memberships`. Mutations return a durable job ID;
inspect `GET /jobs/{id}` for completion or file errors. `POST /jobs/reindex` refreshes the index without
deleting it. The login seed applies only when no administrator exists; changing the environment value
later does not rotate an existing password. Protect and back up the service-state volume.

Production sessions use Secure cookies, so serve the API over HTTPS. For a trusted local HTTP trial,
set `RECOLL_MODERN_DEVELOPMENT_MODE=true`; do not use that setting on a public endpoint. Set
`RECOLL_MODERN_ROOT_PATH=/recoll` when hosting under a path prefix, and make the reverse proxy preserve
that path. `RECOLL_MODERN_TRUSTED_PROXIES` accepts comma-separated IP networks; only forwarded host,
scheme and prefix headers from those networks are honored. The health URL follows the prefix, for
example `/recoll/health`.

To run the generated-corpus container checks, start Compose with a test document containing the unique
word `zebraplatypus`, set `RECOLL_MODERN_TEST_CORPUS_FILE` to its path relative to the document root,
and run `RECOLL_MODERN_REQUIRE_DOCKER=1 uv run pytest tests/integration`. Ordinary host test runs skip
these checks when Compose is not running. Recoll commands run only inside the container.

Working here (human or agent): read [`AGENTS.md`](AGENTS.md). It is the single source of truth for
commands, workflow, and boundaries. Deeper context lives in [`docs/`](docs/).
