#!/bin/sh
set -eu
usage() { echo "$*" >&2; exit 2; }

action=${1:-}
project=${2:-}
case "$project" in csi-benchmark-[a-z0-9]* ) ;; *) usage 'Usage: ./dev benchmark:* <csi-benchmark-name> ...' ;; esac
[ "${#project}" -le 63 ] || exit 2
password_file=".env.benchmark.$project"
dataset="generated-data/$project/benchmark"
port=${CSI_WEB_PORT:-18090}
case "$port" in ''|*[!0-9]*) echo 'CSI_WEB_PORT must be numeric.' >&2; exit 2 ;; esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || exit 2

preflight() {
  command -v docker >/dev/null && command -v k6 >/dev/null && command -v uv >/dev/null || {
    echo 'Docker, k6 and uv are required for the host benchmark.' >&2; exit 1;
  }
  free=$(df -Pk . | awk 'NR==2 {print $4}')
  [ "$free" -ge 4194304 ] || { echo 'Benchmark requires at least 4 GiB host disk free.' >&2; exit 1; }
  memory=$(docker info --format '{{.MemTotal}}')
  [ "$memory" -ge 4294967296 ] || { echo 'Benchmark requires at least 4 GiB Docker memory.' >&2; exit 1; }
  echo "Preflight: host free ${free} KiB; Docker memory ${memory} bytes; project $project"
}

check_port() {
  current=$(CSI_WEB_PORT="$port" docker compose -p "$project" port web 8080 2>/dev/null || true)
  [ "$current" = "127.0.0.1:$port" ] && return
  python3 - "$port" <<'PY' || { echo "Host port $port is unavailable; set CSI_WEB_PORT." >&2; exit 1; }
import socket, sys
with socket.socket() as listener:
    listener.bind(('127.0.0.1', int(sys.argv[1])))
PY
}

check_target() {
  current=$(CSI_WEB_PORT="$port" docker compose -p "$project" port web 8080 2>/dev/null || true)
  [ "$current" = "127.0.0.1:$port" ] || { echo 'Selected benchmark project does not own the requested web port.' >&2; exit 1; }
  expected=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["dataset_id"])' "$dataset/manifest.json")
  actual=$(docker compose -p "$project" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U customer_insights -d customer_insights -Atc "SELECT dataset_id FROM dataset_instance"' | tr -d '\r\n')
  [ "$actual" = "$expected" ] || { echo 'Benchmark dataset identity differs from the named project.' >&2; exit 1; }
}

case "$action" in
  metrics)
    [ "$#" -eq 4 ] || usage 'Usage: ./dev benchmark:metrics <csi-benchmark-name> warm|load|overload|recovery <seconds>'
    case "$3" in warm|load|overload|recovery) ;; *) usage 'Use a named metrics phase.' ;; esac
    case "$4" in ''|*[!0-9]*) usage 'Metrics duration must be an integer.' ;; esac
    [ "$4" -ge 1 ] && [ "$4" -le 360 ] || usage 'Metrics duration must be 1-360 seconds.'
    check_target
    result_root=${CSI_RESULTS_DIR:-"$HOME/Documents/Capitec Application/benchmark-results"}
    case "$result_root" in "$PWD"|"$PWD"/*) fail='Results must be outside Git.'; echo "$fail" >&2; exit 2 ;; esac
    umask 077
    mkdir -p "$result_root/$project"
    result="$result_root/$project/metrics-$3-$(date -u +%Y%m%dT%H%M%SZ).jsonl"
    python3 tools/benchmark/collect-metrics.py "$project" "$3" "$4" > "$result"
    echo "Private metrics: $result"
    ;;
  prepare)
    [ "$#" -eq 3 ] && [ "$3" = "$project" ] || usage 'Usage: ./dev benchmark:prepare <csi-benchmark-name> <same-name-to-approve>'
    preflight
    check_port
    [ -f .env ] || { echo 'Missing .env.' >&2; exit 1; }
    if [ ! -f "$password_file" ]; then
      docker volume inspect "${project}_postgres-data" >/dev/null 2>&1 && {
        echo 'Existing benchmark volume has no local login file; refusing to change credentials.' >&2; exit 1;
      }
      umask 077
      printf 'CSI_CUSTOMER_PASSWORD=%s\n' "$(od -An -tx1 -N 24 /dev/urandom | tr -d ' \n')" > "$password_file"
    fi
    chmod 600 "$password_file"
    if [ ! -e "$dataset" ]; then
      mkdir -p "generated-data/$project"
      (cd tools/data-generator && uv run --locked python -m csi_data generate benchmark "../../$dataset")
    fi
    (cd tools/data-generator && uv run --locked python -m csi_data validate "../../$dataset")
    docker compose -p "$project" up -d --wait db
    docker compose -p "$project" run --rm db-migrate
    docker compose -p "$project" run --rm db-provision
    set -a
    . "./$password_file"
    set +a
    (cd tools/data-generator && uv run --locked python -m csi_data import "../../$dataset" --project "$project" --approve-target "$project")
    CSI_WEB_PORT="$port" docker compose -p "$project" up -d --build --wait api web
    echo "Benchmark ready: http://127.0.0.1:$port"
    ;;
  run)
    [ "$#" -eq 4 ] || usage 'Usage: ./dev benchmark:run <csi-benchmark-name> smoke|compare|reference|hpa <comma-separated-login-ids>'
    preflight
    [ -f "$password_file" ] || { echo 'Benchmark login file missing; run benchmark:prepare first.' >&2; exit 1; }
    check_target
    case "$3" in smoke) rate=10; duration=30s ;; compare) rate=50; duration=30s ;; reference) rate=50; duration=5m ;; hpa) rate=50; duration=2m ;; *) usage 'Usage: profile must be smoke, compare, reference or hpa.' ;; esac
    origin=${CSI_BENCHMARK_ORIGIN:-"http://127.0.0.1:$port"}
    case "$origin" in "http://127.0.0.1:$port"|http://127.0.0.1:18091) ;; *) usage 'Usage: CSI_BENCHMARK_ORIGIN must be an approved loopback benchmark origin.' ;; esac
    [ "$3" != hpa ] || [ "$origin" = http://127.0.0.1:18091 ] || usage 'Usage: hpa profile requires the local k3d origin.'
    printf '%s' "$4" | tr ',' '\n' | while IFS= read -r login; do
      case "$login" in synthetic-[0-9][0-9][0-9][0-9][0-9]) ;; *) echo 'Use synthetic benchmark login IDs.' >&2; exit 2 ;; esac
    done
    result_root=${CSI_RESULTS_DIR:-"$HOME/Documents/Capitec Application/benchmark-results"}
    case "$result_root" in "$PWD"|"$PWD"/*) echo 'Results must be outside Git.' >&2; exit 2 ;; esac
    umask 077
    mkdir -p "$result_root/$project"
    result="$result_root/$project/$3-$(date -u +%Y%m%dT%H%M%SZ).json"
    set -a
    . "./$password_file"
    set +a
    CSI_ORIGIN="$origin" CSI_LOGIN_IDS="$4" CSI_RATE="$rate" CSI_DURATION="$duration" \
      k6 run --summary-export "$result" tools/benchmark/financial-reads.js
    echo "Private summary: $result"
    ;;
  down)
    [ "$#" -eq 3 ] && [ "$3" = "$project" ] || usage 'Usage: ./dev benchmark:down <csi-benchmark-name> <same-name-to-approve>'
    CSI_WEB_PORT="$port" docker compose -p "$project" down
    echo "Stopped $project; its database volume and credentials remain intact."
    ;;
  *) usage 'Usage: ./dev benchmark:prepare|benchmark:run|benchmark:down ...' ;;
esac
