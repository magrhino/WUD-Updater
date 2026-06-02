FROM node:26-bookworm-slim@sha256:79723b41edbedf595f62e943a9f8b0ba9af5b1e61045c5f8f59c2c02c1212a16 AS webui-build

WORKDIR /webui

COPY webui/package*.json /webui/
RUN npm ci

COPY webui/ /webui/
RUN npm run build


FROM python:3.14.5-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb

ARG TRUENAS_API_CLIENT_REF=""

ENV DEBIAN_FRONTEND=noninteractive \
    DOCKER_BASE=/host/docker \
    WUD_OUT_FILE=/out/images.todo \
    WUD_LOG_DIR=/logs \
    WUD_UPDATER=/app/bin/docker-update-from-wud \
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
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc; \
    chmod a+r /etc/apt/keyrings/docker.asc; \
    . /etc/os-release; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      docker-ce-cli \
      docker-compose-plugin; \
    if [ -n "$TRUENAS_API_CLIENT_REF" ]; then \
      apt-get install -y --no-install-recommends git; \
      python -m pip install --no-cache-dir "git+https://github.com/truenas/api_client.git@${TRUENAS_API_CLIENT_REF}"; \
      apt-get purge -y --auto-remove git; \
    fi; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src/ /app/src/
COPY --from=webui-build /webui/dist/ /app/src/wud_updater/web_static/

RUN python -m pip install --no-cache-dir .

COPY bin/ /app/bin/
COPY wud/ /app/wud/
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh /app/bin/updates /app/bin/docker-update-from-wud /app/wud/*.sh \
    && mkdir -p /host/docker /out /logs

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["updates", "--dry-run"]
