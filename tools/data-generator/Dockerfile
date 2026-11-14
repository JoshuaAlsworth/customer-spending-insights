FROM docker:29.9.3-cli@sha256:5a7af0dcb0e46c803efe9b45371dd21cb500e5b4453250394ac6f06d49b6e6f1 AS docker-cli

FROM python:3.14.10-alpine3.24@sha256:5862d971d1f0ae26b258cefa4e893556b1d3aba81bd2ff30888704ad378bab67 AS runtime
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
WORKDIR /tool
COPY tools/data-generator/pyproject.toml tools/data-generator/uv.lock ./
RUN pip install --no-cache-dir uv==0.13.4 \
    && uv export --locked --no-dev --no-emit-project --quiet -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && python -m pip uninstall -y pip \
    && rm /tmp/requirements.txt
ENTRYPOINT ["python", "-m", "csi_data"]

FROM runtime AS test
RUN uv export --locked --all-groups --no-emit-project --quiet -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
