#!/bin/sh
set -eu

docker info >/dev/null 2>&1 || { echo 'Docker Desktop is unavailable.' >&2; exit 1; }

api() {
  docker run --rm -v "$PWD:$PWD" -w "$PWD/apps/api" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal \
    --entrypoint sh \
    eclipse-temurin:25.0.5_8-jdk-alpine@sha256:c7c3d0bdf7f2bbc5a05a6712ed334d198360105634ea9adf76fca94f381b1e3f \
    -c './gradlew spotlessCheck clean test --no-daemon'
}

web() {
  docker run --rm -v "$PWD:$PWD" -v "$PWD/node_modules" \
    -v "$PWD/apps/web/node_modules" -w "$PWD" --entrypoint sh \
    node:24.19.0-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 \
    -c 'corepack enable && corepack prepare pnpm@12.19.0 --activate && pnpm install --frozen-lockfile && pnpm --filter web api:check && pnpm check && pnpm test && pnpm build'
}

python_checks() {
  docker build -q --target test -f tools/data-generator/Dockerfile -t customer-spending-insights-data-test:local . >/dev/null
  docker run --rm -v "$PWD:$PWD" -w "$PWD/tools/data-generator" \
    -v "$PWD/tools/data-generator/.venv" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -e "PYTHONPATH=$PWD/tools/data-generator" \
    --entrypoint sh customer-spending-insights-data-test:local \
    -c 'ruff check . ../simulator ../dev && ruff format --check . ../simulator ../dev && pytest -q'
}

browser() {
  project="csi-browser-docker-$$"
  port=${CSI_WEB_PORT:-8088}
  if docker volume inspect "${project}_postgres-data" >/dev/null 2>&1 || \
     [ -n "$(docker ps -a --filter "label=com.docker.compose.project=$project" -q)" ]; then
    echo "Isolated browser project $project already exists; refusing to remove its data." >&2
    exit 1
  fi
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'status=$?; docker compose -p "$project" down -v --remove-orphans >/dev/null || status=1; exit "$status"' 0
  CSI_ISOLATED_TEST_DB=1 ./dev fixture "$project"
  docker compose -p "$project" up --build -d --wait web
  docker build -q -f tools/browser-tests/Dockerfile -t customer-spending-insights-browser-test:local . >/dev/null
  for script in account_balances money_signs mobile_navigation category_activation transaction_history simulator_lifecycle; do
    docker run --rm -v "$PWD:$PWD" -w "$PWD" \
      -v "$PWD/tools/data-generator/.venv" \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -e "CSI_COMPOSE_PROJECT=$project" \
      -e "CSI_BROWSER_BASE_URL=http://host.docker.internal:$port" \
      --entrypoint python customer-spending-insights-browser-test:local \
      "tools/browser-tests/$script.py"
  done
}

case "${1:-}" in
  api) api ;;
  web) web ;;
  python) python_checks ;;
  browser) browser ;;
  all)
    api
    web
    python_checks
    docker compose --env-file .env.example config --quiet
    docker compose build api web
    ;;
  *) echo 'Usage: ./dev test:docker <api|web|python|browser|all>' >&2; exit 2 ;;
esac
