#!/bin/sh
set -eu

project=${CSI_COMPOSE_PROJECT:-customer-spending-insights}
port=${CSI_WEB_PORT:-8088}
case "$project" in ''|[!a-z0-9]*|*[!a-z0-9_-]*) echo 'Invalid CSI_COMPOSE_PROJECT' >&2; exit 2;; esac
[ "${#project}" -le 63 ] || { echo 'Invalid CSI_COMPOSE_PROJECT' >&2; exit 2; }
case "$port" in *[!0-9]*|'') echo 'CSI_WEB_PORT must be a port from 1 to 65535' >&2; exit 2;; esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || { echo 'CSI_WEB_PORT must be a port from 1 to 65535' >&2; exit 2; }
login_file=".env.demo.$project"
dataset="generated-data/$project/demo"

compose() { docker compose -p "$project" "$@"; }
random_hex() { od -An -tx1 -N "$1" /dev/urandom | tr -d ' \n'; }
fail() { echo "$*" >&2; exit 1; }

check_docker() {
  command -v docker >/dev/null 2>&1 || fail 'Docker CLI is required.'
  docker info >/dev/null 2>&1 || fail 'Docker Desktop is unavailable; start it and retry.'
  docker compose version >/dev/null 2>&1 || fail 'Docker Compose is required.'
  docker compose up --help | grep -Fq -- '--wait' || fail 'Docker Compose with up --wait is required.'
  docker compose run --help | grep -Fq -- '--no-deps' || fail 'Docker Compose with run --no-deps is required.'
  docker ps -a --filter "label=com.docker.compose.project=$project" \
    --format '{{.Label "com.docker.compose.project.working_dir"}}' \
    | while IFS= read -r owner; do
        [ -z "$owner" ] || [ "$owner" = "$PWD" ] || {
          echo "Compose project $project belongs to another directory." >&2
          exit 1
        }
      done
}

create_config() {
  [ -e .env ] && return
  umask 077
  temporary=$(mktemp .env.XXXXXX)
  {
    printf 'POSTGRES_PASSWORD=%s\n' "$(random_hex 24)"
    printf 'API_DB_PASSWORD=%s\n' "$(random_hex 24)"
    printf 'CURSOR_SECRET=%s\n' "$(random_hex 32)"
    printf 'SIMULATOR_DB_PASSWORD=%s\n' "$(random_hex 24)"
  } > "$temporary"
  ln "$temporary" .env 2>/dev/null || true
  rm -f "$temporary"
}

validate_config() {
  [ -f .env ] || fail 'Missing .env.'
  chmod 600 .env 2>/dev/null || true
  for key in POSTGRES_PASSWORD API_DB_PASSWORD CURSOR_SECRET SIMULATOR_DB_PASSWORD; do
    count=$(awk -F= -v key="$key" '$1 == key { n++ } END { print n+0 }' .env)
    [ "$count" -eq 1 ] || fail "Expected exactly one $key in .env."
    value=$(sed -n "s/^$key=//p" .env)
    [ "${#value}" -ge 24 ] || fail "$key must contain at least 24 characters."
    case "$value" in *replace*|*REPLACE*|*' '*|*'\$'*|*'`'*) fail "Invalid $key in .env.";; esac
  done
  cursor=$(sed -n 's/^CURSOR_SECRET=//p' .env)
  [ "${#cursor}" -eq 64 ] || fail 'CURSOR_SECRET must be 64 hexadecimal characters.'
  case "$cursor" in *[!0-9a-fA-F]*) fail 'CURSOR_SECRET must be hexadecimal.';; esac
  admin=$(sed -n 's/^POSTGRES_PASSWORD=//p' .env)
  api=$(sed -n 's/^API_DB_PASSWORD=//p' .env)
  sim=$(sed -n 's/^SIMULATOR_DB_PASSWORD=//p' .env)
  [ "$admin" != "$api" ] && [ "$admin" != "$sim" ] && [ "$api" != "$sim" ] || fail 'Infrastructure passwords must be distinct.'
  if [ "${API_DB_PASSWORD+x}" = x ] && [ "$API_DB_PASSWORD" != "$api" ]; then
    fail 'API_DB_PASSWORD environment override differs from .env; use the configured credential.'
  fi
  if [ "${SIMULATOR_DB_PASSWORD+x}" = x ] && [ "$SIMULATOR_DB_PASSWORD" != "$sim" ]; then
    fail 'SIMULATOR_DB_PASSWORD environment override differs from .env; use the configured credential.'
  fi
  compose config --quiet || fail 'Invalid Compose configuration.'
}

check_port() {
  current=$(compose port web 8080 2>/dev/null || true)
  [ "$current" = "127.0.0.1:$port" ] && return
  docker run --rm -p "127.0.0.1:$port:8080" --entrypoint true \
    postgres:17.7-alpine@sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2 \
    >/dev/null 2>&1 || fail "Host port $port is unavailable. Set CSI_WEB_PORT to an available port."
}

tool() {
  env_file=$1
  shift
  docker run --rm \
    --env-file "${env_file:-/dev/null}" \
    -v "$PWD:$PWD" -w "$PWD" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -e "PYTHONPATH=$PWD/tools/data-generator" \
    -e "CSI_COMPOSE_PROJECT=$project" \
    --entrypoint python customer-spending-insights-data-tool:local \
    -m csi_data "$@"
}

dataset_state() {
  compose --profile tools run --rm -T --no-deps --entrypoint psql db-import \
    -X -q -A -t -v ON_ERROR_STOP=1 -h db -U customer_insights -d customer_insights \
    -c "SELECT CASE WHEN EXISTS (SELECT 1 FROM dataset_instance) THEN 'seeded' WHEN EXISTS (SELECT 1 FROM customers) THEN 'partial' ELSE 'empty' END" \
    | tr -d '\r\n'
}

check_api_password() {
  exists=$(compose --profile tools run --rm -T --no-deps --entrypoint psql db-import \
    -X -q -A -t -v ON_ERROR_STOP=1 -h db -U customer_insights -d customer_insights \
    -c "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'customer_insights_api')" | tr -d '\r\n')
  if [ "$exists" = t ]; then
    compose run --rm -T --no-deps --entrypoint sh db-provision \
      -c 'PGPASSWORD="$API_DB_PASSWORD" psql -X -q -A -t -v ON_ERROR_STOP=1 -h db -U customer_insights_api -d customer_insights -c "SELECT 1"' \
      >/dev/null 2>&1 || fail 'Existing API database password differs from .env; restore the original configuration. No password was rotated.'
  else
    [ "$exists" = f ] || fail 'Could not verify the API database role.'
  fi
}

make_login() {
  [ ! -e "$login_file" ] || return
  umask 077
  temporary=$(mktemp .env.demo.XXXXXX)
  printf 'CSI_CUSTOMER_PASSWORD=%s\n' "$(random_hex 24)" > "$temporary"
  ln "$temporary" "$login_file" 2>/dev/null || true
  rm -f "$temporary"
}

validate_login() {
  [ -f "$login_file" ] || fail "Missing $login_file. Existing credentials cannot be recovered."
  count=$(awk -F= '$1 == "CSI_CUSTOMER_PASSWORD" { n++ } END { print n+0 }' "$login_file")
  [ "$count" -eq 1 ] || fail "Invalid $login_file."
  password=$(sed -n 's/^CSI_CUSTOMER_PASSWORD=//p' "$login_file")
  [ "${#password}" -eq 48 ] || fail "Invalid $login_file."
  case "$password" in *[!0-9a-f]*) fail "Invalid $login_file.";; esac
  chmod 600 "$login_file" 2>/dev/null || true
}

up() {
  check_docker
  check_port
  create_config
  validate_config
  echo "Starting Compose project $project on 127.0.0.1:$port"
  compose up -d --wait db
  compose run --rm db-migrate
  check_api_password
  compose run --rm db-provision
  state=$(dataset_state)
  case "$state" in
    empty)
      docker build -q --target runtime -f tools/data-generator/Dockerfile -t customer-spending-insights-data-tool:local . >/dev/null
      mkdir -p "generated-data/$project"
      if [ ! -e "$dataset" ]; then
        temporary="generated-data/$project/.demo-build-$$"
        trap 'rm -rf "$temporary"' 0 HUP INT TERM
        tool '' generate demo "$temporary"
        mv "$temporary" "$dataset"
        trap - 0 HUP INT TERM
      fi
      tool '' validate "$dataset"
      make_login
      validate_login
      tool "$login_file" import "$dataset" --project "$project" --approve-target "$project"
      ;;
    seeded) echo 'Preserving existing financial dataset.' ;;
    *) fail 'Database has financial rows without an approved dataset identity; inspect it before retrying.' ;;
  esac
  compose up --no-deps --build -d --wait api
  compose up --no-deps --build -d --wait web
  compose exec -T web wget -q -O /dev/null http://127.0.0.1:8080/ || fail 'Web readiness failed; inspect ./dev logs.'
  echo "Ready: http://127.0.0.1:$port"
  if [ -f "$login_file" ]; then
    validate_login
    echo 'Demo login: synthetic-00004; run ./dev credentials for the local password.'
  else
    echo 'Existing dataset: use its original synthetic login credentials.'
  fi
}

case "${1:-}" in
  up) up ;;
  down) check_docker; compose down ;;
  status) check_docker; compose ps ;;
  logs) check_docker; compose logs --tail=80 db api web ;;
  credentials)
    [ -f "$login_file" ] || fail 'No local demo login file. Existing datasets retain their original credentials.'
    validate_login
    echo 'Login ID: synthetic-00004'
    sed 's/^CSI_CUSTOMER_PASSWORD=/Password: /' "$login_file"
    ;;
  demo)
    [ "$#" -eq 3 ] && [ "$3" = --approve ] || fail 'Usage: ./dev demo <run-id> --approve'
    validate_config
    check_docker
    docker build -q --target runtime -f tools/data-generator/Dockerfile -t customer-spending-insights-data-tool:local . >/dev/null
    docker run --rm -v "$PWD:$PWD" -w "$PWD" \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -e "PYTHONPATH=$PWD/tools/data-generator" -e "CSI_COMPOSE_PROJECT=$project" \
      --entrypoint python customer-spending-insights-data-tool:local \
      tools/dev/demo.py "$2" --approve
    ;;
  *) fail 'Usage: ./dev {up|down|status|logs|credentials|demo}' ;;
esac
