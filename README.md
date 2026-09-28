# recoll-modern

A modern, self-hosted web UI and MCP server on top of [Recoll](https://www.lesbonscomptes.com/recoll/)
full-text search, with support for multiple independent collections.

Status: spec 001's authenticated search API and Docker deployment have completed acceptance and
review checks. The web UI and MCP server are later specs.

## Published Docker image

The image is `gitea.lucaswinther.info/lucasw89/recoll-modern` for `linux/amd64`. It currently contains
the authenticated search API and Recoll; the web UI and MCP server are later specs. `:main` follows
the main branch. A release tag such as `:v1.2.3` pins a specific release; `:latest` follows the newest
version tag. Use a version tag when you want a predictable update. The image records its source,
revision and version in OCI labels (`docker image inspect IMAGE`).

### Run the pulled image with Compose

Save [compose.published.yaml](compose.published.yaml) alongside this guide, or download it from the
repository after the publishing branch reaches `main`:

```sh
curl -fL -o compose.published.yaml \
  https://gitea.lucaswinther.info/lucasw89/recoll-modern/raw/branch/main/compose.published.yaml
```

If the package is private, log in to the Gitea registry first. Use your Gitea username and a personal
access token with package **Read** permission as the Docker password:

```sh
docker login gitea.lucaswinther.info
```

Set an absolute host directory for documents and seed the first administrator. `:main` is available
after a successful main-branch publish, even before the first version tag:

```sh
export RECOLL_MODERN_DOCUMENTS=/srv/documents
export RECOLL_MODERN_ADMIN_USERNAME=admin
export RECOLL_MODERN_ADMIN_PASSWORD='use-a-long-unique-password'
export RECOLL_MODERN_IMAGE=gitea.lucaswinther.info/lucasw89/recoll-modern:main
docker compose -f compose.published.yaml pull
docker compose -f compose.published.yaml up -d --no-build
docker compose -f compose.published.yaml ps
docker compose -f compose.published.yaml logs -f app
```

Once a version appears in Gitea Packages, set `RECOLL_MODERN_IMAGE` to its tag, such as
`gitea.lucaswinther.info/lucasw89/recoll-modern:v1.2.3`, to pin that release. Omit
`RECOLL_MODERN_IMAGE` to use `:latest` after the first version tag is published. The image is published
only after the CI checks pass; a tag that has not been published cannot be pulled. To update, set the
desired tag and run `docker compose -f compose.published.yaml pull` followed
by `docker compose -f compose.published.yaml up -d --no-build` again. Keep the same Compose project
directory so its named volumes are reused.

For a trusted local HTTP trial with `docker run`, use the same document and administrator variables:

```sh
export RECOLL_MODERN_IMAGE=${RECOLL_MODERN_IMAGE:-gitea.lucaswinther.info/lucasw89/recoll-modern:main}
docker pull "$RECOLL_MODERN_IMAGE"
docker run -d --name recoll-modern --restart unless-stopped -p 127.0.0.1:8000:8000 \
  -e RECOLL_MODERN_ADMIN_USERNAME -e RECOLL_MODERN_ADMIN_PASSWORD \
  -e RECOLL_MODERN_HOST=0.0.0.0 -e RECOLL_MODERN_PORT=8000 \
  -e RECOLL_MODERN_DEVELOPMENT_MODE=true \
  --mount "type=bind,src=$RECOLL_MODERN_DOCUMENTS,dst=/documents,readonly" \
  --mount type=volume,src=recoll-modern-service-state,dst=/var/lib/recoll-modern \
  --mount type=volume,src=recoll-modern-index,dst=/var/lib/recoll \
  "$RECOLL_MODERN_IMAGE"
```

### Build locally

The original `compose.yaml` still builds from this repository:

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

For the direct `docker run` example, the volumes are named `recoll-modern-service-state` and
`recoll-modern-index`. Back up both together. Replacing a container does not delete these volumes.

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

## Publishing from Gitea

Enable repository Actions and use a runner with the `ubuntu-latest` label, Python 3, `uv` setup support,
and a working Docker CLI/daemon. In the repository's Actions secrets, set `REGISTRY_USERNAME` to the
Gitea account that owns the publishing token and `REGISTRY_TOKEN` to a personal access token with
package **Read & Write** permission. Gitea currently [requires a PAT for Actions package
publishing](https://docs.gitea.com/usage/actions/comparison/); the built-in job token does not publish
OCI packages. The workflow checks pull requests without registry credentials and publishes only after
checks pass on `main` or a full `vX.Y.Z` tag. No server deployment is performed by CI.

Working here (human or agent): read [`AGENTS.md`](AGENTS.md). It is the single source of truth for
commands, workflow, and boundaries. Deeper context lives in [`docs/`](docs/).
