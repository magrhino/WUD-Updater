FROM docker:29.5.3-cli@sha256:873de13208aab9c1de73fe984fd45883e01464fcfcc85efa20aa56a9ccfe7aa6 AS docker-cli

FROM aquasec/trivy:0.71.2@sha256:f5d0e600ecda7449e2a9b272805aef698631d3bb3f3a739a750de2c6819acdc9 AS trivy

FROM node:26-bookworm-slim@sha256:79723b41edbedf595f62e943a9f8b0ba9af5b1e61045c5f8f59c2c02c1212a16 AS webui-build

WORKDIR /webui

COPY webui/package*.json /webui/
RUN npm ci

COPY webui/ /webui/
RUN npm run build


FROM python:3.14.5-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb AS wudup-runtime

ARG TRUENAS_API_CLIENT_REF=""

ENV DEBIAN_FRONTEND=noninteractive \
    DOCKER_BASE=/host/docker \
    WUD_OUT_FILE=/out/images.todo \
    WUD_LOG_DIR=/logs \
    WUD_WEB_HOST=0.0.0.0 \
    WUDUP_UPDATER=/app/bin/docker-update-from-wud \
    PATH=/app/bin:$PATH

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      bash \
      bsdextrautils \
      bsdutils \
      ca-certificates \
      coreutils \
      curl \
      findutils \
      gawk \
      grep \
      jq \
      perl \
      sed \
      sudo \
      tini \
      tzdata \
      util-linux; \
    if [ -n "$TRUENAS_API_CLIENT_REF" ]; then \
      apt-get install -y --no-install-recommends git; \
      python -m pip install --no-cache-dir "git+https://github.com/truenas/api_client.git@${TRUENAS_API_CLIENT_REF}"; \
      apt-get purge -y --auto-remove git; \
    fi; \
    rm -rf /var/lib/apt/lists/*

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

WORKDIR /app

COPY requirements.txt /app/
RUN python -m pip install --require-hashes --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md /app/
COPY src/ /app/src/
COPY --from=webui-build /webui/dist/ /app/src/wudup/web_static/

RUN python -m pip install --no-deps --no-cache-dir .

COPY bin/ /app/bin/
COPY wud/ /app/wud/
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh /app/bin/updates /app/bin/docker-update-from-wud /app/wud/*.sh \
    && mkdir -p /host/docker /out /logs

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD curl -fsS -o /dev/null "http://127.0.0.1:${WUD_WEB_PORT:-7417}/readyz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["web"]

FROM wudup-runtime AS wudup-trivy

COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy

FROM wudup-runtime AS wudup
