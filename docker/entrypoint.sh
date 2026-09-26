#!/bin/sh
set -eu

mkdir -p "${RECOLL_MODERN_STATE_ROOT:-/var/lib/recoll-modern}" \
    /var/lib/recoll "${RECOLL_MODERN_RECOLL_CONFIG_DIR:-/var/lib/recoll-modern/recoll-config}"
config_dir="${RECOLL_MODERN_RECOLL_CONFIG_DIR:-/var/lib/recoll-modern/recoll-config}"
for name in recoll.conf fields; do
    if [ ! -e "$config_dir/$name" ]; then
        cp "/etc/recoll-modern/$name" "$config_dir/$name"
    fi
done
exec recoll-modern
