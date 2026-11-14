"""Sample private, container-local operator metrics during a bounded workload."""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone


METRICS = {
    "heap_used_bytes": "jvm.memory.used?tag=area:heap",
    "heap_committed_bytes": "jvm.memory.committed?tag=area:heap",
    "nonheap_used_bytes": "jvm.memory.used?tag=area:nonheap",
    "gc_pause_seconds": "jvm.gc.pause",
    "jvm_threads_live": "jvm.threads.live",
    "tomcat_threads_busy": "tomcat.threads.busy",
    "tomcat_threads_current": "tomcat.threads.current",
    "hikari_active": "hikaricp.connections.active",
    "hikari_idle": "hikaricp.connections.idle",
    "hikari_pending": "hikaricp.connections.pending",
    "hikari_max": "hikaricp.connections.max",
    "hikari_timeouts": "hikaricp.connections.timeout",
    "session_active": "tomcat.sessions.active.current",
    "executor_active": "executor.active",
    "executor_queued": "executor.queued",
    "http_requests": "http.server.requests",
}


def run(*command: str) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip()


def sample(project: str, phase: str, image: str) -> dict:
    measurements = {}
    for label, metric in METRICS.items():
        try:
            body = run(
                "docker",
                "compose",
                "-p",
                project,
                "exec",
                "-T",
                "api",
                "wget",
                "-qO-",
                f"http://127.0.0.1:8080/actuator/metrics/{metric}",
            )
            measurements[label] = {
                item["statistic"]: item["value"]
                for item in json.loads(body)["measurements"]
            }
        except (subprocess.CalledProcessError, KeyError, ValueError):
            measurements[label] = None
    connection_count = int(
        run(
            "docker",
            "compose",
            "-p",
            project,
            "exec",
            "-T",
            "db",
            "sh",
            "-c",
            'PGPASSWORD="$POSTGRES_PASSWORD" psql -XAt -U customer_insights -d customer_insights -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"',
        )
    )
    containers = {}
    for line in run(
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
        *[f"{project}-{service}-1" for service in ("api", "db", "web")],
    ).splitlines():
        item = json.loads(line)
        containers[item["Name"]] = {
            "cpu": item["CPUPerc"],
            "memory": item["MemUsage"],
            "memory_limit": item["MemPerc"],
        }
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "api_image": image,
        "metrics": measurements,
        "database_connections": connection_count,
        "containers": containers,
    }


def main() -> None:
    project, phase, duration = sys.argv[1:]
    duration = int(duration)
    image = run("docker", "compose", "-p", project, "images", "api", "-q")
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        print(json.dumps(sample(project, phase, image), separators=(",", ":")), flush=True)
        time.sleep(max(0, min(5, deadline - time.monotonic())))


if __name__ == "__main__":
    main()
