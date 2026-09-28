#!/usr/bin/env bash
set -euo pipefail

tags=$(python3 scripts/image_tags.py "$GITHUB_REF")
if [[ -z "$tags" ]]; then
  exit 0
fi

export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
trap 'rm -r "$DOCKER_CONFIG"' EXIT

printf '%s' "$REGISTRY_TOKEN" |
  docker login gitea.lucaswinther.info --username "$REGISTRY_USERNAME" --password-stdin

image_id=$(docker build --quiet --platform linux/amd64 \
  --label "org.opencontainers.image.source=https://gitea.lucaswinther.info/lucasw89/recoll-modern" \
  --label "org.opencontainers.image.description=Self-hosted Recoll search API" \
  --label "org.opencontainers.image.revision=$GITHUB_SHA" \
  --label "org.opencontainers.image.version=$GITHUB_REF_NAME" .)

while IFS= read -r image; do
  docker tag "$image_id" "$image"
  docker push "$image"
done <<< "$tags"
