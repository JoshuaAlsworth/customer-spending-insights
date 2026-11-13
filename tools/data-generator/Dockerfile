FROM docker:29.2.1-cli@sha256:cab69e2d0a1a2ea9a1ce1060252f439e83483ae41ec09317aecb33b08a0656a5 AS docker-cli

FROM python:3.14.6-slim-bookworm@sha256:4c92ffcde4dd6f1ff72a24518f49fd4990b27134987dfa31a733badde66df9f8 AS runtime
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
WORKDIR /tool
COPY tools/data-generator/pyproject.toml tools/data-generator/uv.lock ./
RUN pip install --no-cache-dir uv==0.11.28 \
    && uv export --locked --no-dev --no-emit-project --quiet -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
ENTRYPOINT ["python", "-m", "csi_data"]

FROM runtime AS test
RUN uv export --locked --all-groups --no-emit-project --quiet -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
