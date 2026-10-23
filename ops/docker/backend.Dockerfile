FROM ubuntu:26.04@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78 AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /usr/local/bin/uv
# 保留已驗證的轉檔版本；一般套件站不保證保存已被取代的版本。
# Ubuntu snapshot：https://snapshot.ubuntu.com/
ARG UBUNTU_SNAPSHOT=20261005T060000Z
# 安全套件另用新快照，避免連帶更換已驗證的 LibreOffice／Bubblewrap。
ARG UBUNTU_SECURITY_SNAPSHOT=20261023T060000Z
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && apt-get update --snapshot "$UBUNTU_SNAPSHOT" \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --snapshot "$UBUNTU_SNAPSHOT" \
    tzdata bubblewrap fontconfig fonts-noto-cjk \
    libreoffice-writer-nogui=4:26.2.5.2-0ubuntu0.26.04.1 \
    libreoffice-impress-nogui=4:26.2.5.2-0ubuntu0.26.04.1 \
    && apt-get update --snapshot "$UBUNTU_SECURITY_SNAPSHOT" \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --snapshot "$UBUNTU_SECURITY_SNAPSHOT" \
       ca-certificates=20260816ubuntu0.26.04.1 \
       libxml2-16=2.15.2+dfsg-0.1ubuntu0.3 \
       libcurl4t64=8.18.0-1ubuntu2.8 \
       libcurl3t64-gnutls=8.18.0-1ubuntu2.8 \
       libfreetype6=2.14.2+dfsg-1ubuntu0.2 \
       libpng16-16t64=1.6.57-1ubuntu0.1 \
       libpoppler156=26.01.0-2ubuntu0.3 \
       libx11-6=2:1.8.13-1ubuntu0.1 \
       libx11-data=2:1.8.13-1ubuntu0.1 \
       zlib1g=1:1.3.dfsg+really1.3.1-1ubuntu3.2 \
       openssl=3.5.5-1ubuntu3.7 \
       libssl3t64=3.5.5-1ubuntu3.7 \
       openssl-provider-legacy=3.5.5-1ubuntu3.7 \
    && rm -rf /var/lib/apt/lists/*
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN uv python install 3.12.15 && chmod -R a+rX /opt/python
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock /app/backend/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --project backend --locked --no-dev --python 3.12.15 \
    && chmod -R a+rX /app/backend/.venv
ENV PYTHONPATH=/app/backend/src \
    PYTHONDONTWRITEBYTECODE=1 \
    STUDYDY_PROFILE=local \
    STUDYDY_LOCAL_RUNTIME_ROOT=/opt/studydy \
    STUDYDY_ARTIFACT_ROOT=/data/artifacts \
    XDG_CACHE_HOME=/tmp/cache \
    HF_HOME=/tmp/huggingface

FROM dependencies AS backend
COPY backend/src /app/backend/src
COPY backend/migrations /app/backend/migrations
COPY local_ai/runtime-lock.json /app/local_ai/runtime-lock.json
RUN chmod -R a+rX /app/backend/src /app/backend/migrations /app/local_ai
USER 20002:1000
ENTRYPOINT ["/app/backend/.venv/bin/python", "-m", "runtime.container_app"]
CMD ["serve"]

FROM backend AS test
USER root
RUN --mount=type=cache,target=/root/.cache/uv uv sync --project backend --locked --no-dev --extra test --python 3.12.15
COPY backend/tests /app/backend/tests
RUN chmod -R a+rX /app
ENV PYTHONPATH=/app/backend/src:/app/backend/tests
USER 20002:1000
ENTRYPOINT ["/app/backend/.venv/bin/pytest"]
CMD ["-q", "-o", "cache_dir=/tmp/pytest-cache", "backend/tests", "--ignore=backend/tests/runtime"]

FROM dependencies AS ssh-bridge
RUN apt-get update --snapshot "$UBUNTU_SECURITY_SNAPSHOT" \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --snapshot "$UBUNTU_SECURITY_SNAPSHOT" \
       openssh-client=1:10.2p1-2ubuntu3.8 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/src/runtime/ssh_bridge.py /app/ssh_bridge.py
RUN chmod 644 /app/ssh_bridge.py
USER 1000:1000
ENTRYPOINT ["/app/backend/.venv/bin/python", "/app/ssh_bridge.py"]
