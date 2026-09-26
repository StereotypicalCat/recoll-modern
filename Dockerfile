FROM debian:trixie-slim AS helper-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY helper/recoll_membership.c ./
RUN cc -std=c17 -O2 -Wall -Wextra -Werror recoll_membership.c -o recoll-membership

FROM ghcr.io/astral-sh/uv:0.12.16 AS uv-bin

FROM debian:trixie-slim
COPY --from=uv-bin /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 python3-recoll recoll poppler-utils python3-lxml unzip \
    && rm -rf /var/lib/apt/lists/*
COPY --from=helper-build /build/recoll-membership /usr/local/bin/recoll-membership
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv venv --python /usr/bin/python3 --system-site-packages /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    RECOLL_MODERN_DOCUMENT_ROOT=/documents \
    RECOLL_MODERN_STATE_ROOT=/var/lib/recoll-modern \
    RECOLL_MODERN_RECOLL_CONFIG_DIR=/var/lib/recoll-modern/recoll-config \
    RECOLL_MODERN_MEMBERSHIP_MAP=/var/lib/recoll-modern/membership.map
RUN uv sync --locked --no-dev && python -c 'from recoll import recoll'
COPY docker/recoll.conf docker/fields /etc/recoll-modern/
COPY docker/entrypoint.sh /usr/local/bin/recoll-modern-entrypoint
RUN chmod 755 /usr/local/bin/recoll-modern-entrypoint \
    && groupadd --gid 10001 recoll-modern \
    && useradd --uid 10001 --gid 10001 --home-dir /var/lib/recoll-modern \
       --shell /usr/sbin/nologin recoll-modern \
    && mkdir -p /documents /var/lib/recoll-modern /var/lib/recoll \
    && chown -R 10001:10001 /var/lib/recoll-modern /var/lib/recoll
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["recoll-modern-entrypoint"]
