FROM python:3.14-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    DOCKER_BASE=/host/docker \
    WUD_OUT_FILE=/out/images.todo \
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
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY bin/ /app/bin/
COPY wud/ /app/wud/
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh /app/bin/updates /app/bin/docker-update-from-wud /app/wud/*.sh \
    && mkdir -p /host/docker /out

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["updates", "--dry-run"]
