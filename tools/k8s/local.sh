#!/bin/sh
set -eu

usage() { echo "$*" >&2; exit 2; }
fail() { echo "$*" >&2; exit 1; }
action=${1:-}
project=${2:-}
cluster=${3:-}
case "$project" in csi-benchmark-[a-z0-9]*) ;; *) usage 'Usage: ./dev k8s:up <csi-benchmark-project> <csi-hardening-cluster>' ;; esac
case "$cluster" in csi-hardening-[a-z0-9]*) ;; *) usage 'Use an explicit csi-hardening-<name> cluster.' ;; esac

case "$action" in
  up)
    [ "$#" -eq 3 ] || usage 'Usage: ./dev k8s:up <csi-benchmark-project> <csi-hardening-cluster>'
    command -v k3d >/dev/null && command -v kubectl >/dev/null && command -v docker >/dev/null || fail 'k3d, kubectl and Docker are required.'
    [ -f .env ] && [ -f ".env.benchmark.$project" ] || fail 'Prepare the isolated benchmark first.'
    docker network inspect "${project}_default" >/dev/null 2>&1 || fail 'Benchmark Docker network is unavailable.'
    [ -z "$(k3d cluster list --no-headers | awk -v name="$cluster" '$1==name {print $1}')" ] || fail 'Cluster already exists; refusing to replace it.'
    free=$(df -Pk . | awk 'NR==2 {print $4}')
    [ "$free" -ge 6291456 ] || fail 'k3d requires at least 6 GiB free host disk.'
    memory=$(docker info --format '{{.MemTotal}}')
    [ "$memory" -ge 7516192768 ] || fail 'k3d requires at least 7 GiB Docker memory.'
    active_mib=$(docker stats --no-stream --format '{{.MemUsage}}' | python3 -c '
import re, sys
total = 0.0
for line in sys.stdin:
    match = re.match(r"\s*([0-9.]+)([KMG]iB)", line)
    if not match:
        continue
    value, unit = match.groups()
    total += float(value) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[unit]
print(int(total))')
    [ "$active_mib" -le 4096 ] || fail 'Running Docker containers already use over 4 GiB; k3d preflight aborted.'
    python3 - <<'PY' || fail 'Required loopback k3d port is unavailable.'
import socket
for port in (16551, 18091):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', port))
PY
    db_ip=$(docker inspect "${project}-db-1" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["NetworkSettings"]["Networks"][sys.argv[1]]["IPAddress"])' "${project}_default")
    [ -n "$db_ip" ] || fail 'Could not resolve isolated benchmark database IP.'
    web_ip=$(docker inspect "${project}-web-1" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["NetworkSettings"]["Networks"][sys.argv[1]]["IPAddress"])' "${project}_default")
    dataset=$(docker compose -p "$project" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U customer_insights -d customer_insights -Atc "SELECT dataset_id FROM dataset_instance"' | tr -d '\r\n')
    case "$dataset" in synthetic-benchmark-*) ;; *) fail 'Benchmark database is not seeded.' ;; esac
    image=$(docker compose -p "$project" images api -q)
    [ -n "$image" ] || fail 'Benchmark API image is missing.'
    echo "Preflight: dataset $dataset; host disk ${free} KiB; Docker memory ${memory} bytes; active containers ${active_mib} MiB; API image $image"
    k3d cluster create "$cluster" --servers 1 --agents 2 \
      --network "${project}_default" --api-port 127.0.0.1:16551 \
      --port 127.0.0.1:18091:80@loadbalancer \
      --k3s-node-label "csi.role=worker@agent:0" \
      --k3s-node-label "csi.role=worker@agent:1" \
      --kubeconfig-switch-context=false --wait --timeout 3m
    docker tag "$image" csi-hardening-api:latest
    k3d image import csi-hardening-api:latest -c "$cluster"
    context="k3d-$cluster"
    crd_ready=0
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do
      if kubectl --context "$context" get crd/middlewares.traefik.io >/dev/null 2>&1; then
        crd_ready=1
        break
      fi
      sleep 5
    done
    [ "$crd_ready" -eq 1 ] || fail 'Traefik Middleware CRD was not installed.'
    kubectl --context "$context" wait --for=condition=Established crd/middlewares.traefik.io --timeout=30s
    kubectl --context "$context" create namespace customer-spending-insights
    temporary=$(mktemp -d)
    chmod 700 "$temporary"
    trap 'rm -rf "$temporary"' EXIT HUP INT TERM
    api_password=$(sed -n 's/^API_DB_PASSWORD=//p' .env)
    cursor_secret=$(sed -n 's/^CURSOR_SECRET=//p' .env)
    printf '%s' "$api_password" > "$temporary/DATABASE_PASSWORD"
    printf '%s' "$cursor_secret" > "$temporary/CURSOR_SECRET"
    printf 'jdbc:postgresql://%s:5432/customer_insights' "$db_ip" > "$temporary/DATABASE_URL"
    printf 'customer_insights_api' > "$temporary/DATABASE_USER"
    kubectl --context "$context" -n customer-spending-insights create secret generic csi-api-db \
      --from-file="DATABASE_PASSWORD=$temporary/DATABASE_PASSWORD" \
      --from-file="DATABASE_URL=$temporary/DATABASE_URL" \
      --from-file="DATABASE_USER=$temporary/DATABASE_USER"
    kubectl --context "$context" -n customer-spending-insights create secret generic csi-api-cursor \
      --from-file="CURSOR_SECRET=$temporary/CURSOR_SECRET"
    kubectl --context "$context" apply -f infra/k8s/api.yaml
    kubectl --context "$context" -n customer-spending-insights rollout status deployment/csi-api --timeout=3m
    kubectl --context "$context" -n customer-spending-insights exec deployment/csi-api -- \
      wget -T 3 -q -O /dev/null "http://$web_ip:8080/" || fail 'Cannot verify baseline pod egress before applying NetworkPolicy.'
    kubectl --context "$context" apply -f - <<YAML
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: csi-api
  namespace: customer-spending-insights
spec:
  podSelector:
    matchLabels: {app: csi-api}
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels: {kubernetes.io/metadata.name: kube-system}
  egress:
    - to:
        - ipBlock: {cidr: "$db_ip/32"}
      ports:
        - {protocol: TCP, port: 5432}
YAML
    sleep 5
    if kubectl --context "$context" -n customer-spending-insights exec deployment/csi-api -- \
      wget -T 3 -q -O /dev/null "http://$web_ip:8080/"; then
      fail 'NetworkPolicy did not deny unrelated web egress.'
    fi
    curl -fsS "http://127.0.0.1:18091/api/v1/auth/csrf" >/dev/null || fail 'Ingress/API failed after NetworkPolicy.'
    metrics_ready=0
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
      if kubectl --context "$context" -n customer-spending-insights top pods >/dev/null 2>&1; then
        metrics_ready=1
        break
      fi
      sleep 5
    done
    [ "$metrics_ready" -eq 1 ] || fail 'Metrics Server did not provide Pod CPU metrics.'
    kubectl --context "$context" -n customer-spending-insights get hpa,pods -o wide
    echo "k3d API ingress: http://127.0.0.1:18091/api/v1/ (local HTTP profile)"
    ;;
  down)
    [ "$#" -eq 4 ] && [ "$4" = "$cluster" ] || usage 'Usage: ./dev k8s:down <csi-benchmark-project> <csi-hardening-cluster> <same-cluster-to-approve>'
    k3d cluster delete "$cluster"
    ;;
  demo)
    [ "$#" -eq 5 ] || usage 'Usage: ./dev k8s:demo <csi-benchmark-project> <csi-hardening-cluster> smoke|compare|reference|hpa <comma-separated-login-ids>'
    [ "$4" = smoke ] || [ "$4" = compare ] || [ "$4" = reference ] || [ "$4" = hpa ] || usage 'Usage: load profile must be smoke, compare, reference or hpa.'
    owner=$(docker ps --filter publish=18091 --format '{{.Names}}' | head -n 1)
    [ "$owner" = "k3d-$cluster-serverlb" ] || fail 'The named k3d cluster does not own loopback port 18091.'
    kubectl --context "k3d-$cluster" -n customer-spending-insights rollout status deployment/csi-api --timeout=60s
    CSI_BENCHMARK_ORIGIN=http://127.0.0.1:18091 sh tools/benchmark/local.sh run "$project" "$4" "$5"
    ;;
  *) usage 'Usage: ./dev k8s:up|k8s:demo|k8s:down ...' ;;
esac
