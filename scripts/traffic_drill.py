#!/usr/bin/env python3
"""
Cloud Run Serverless CI/CD & Canary Traffic Splitting Drill
===========================================================
Concurrently dispatches HTTP requests to a Cloud Run service's `/api/info`
endpoint, parses live container & revision telemetry (`version`, `revision`,
`container_id`, `cold_start`), and renders an executive traffic report.
"""

import argparse
import collections
import concurrent.futures
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_SERVICE_NAME = os.getenv("SERVICE_NAME", "smg-serverless-app")
DEFAULT_REGION = os.getenv("REGION", "asia-southeast2")
DEFAULT_PROJECT_ID = os.getenv("PROJECT_ID", "dev-robifirmansyah")


def resolve_default_service_url() -> str:
    """
    Attempt to resolve the live Cloud Run service URL via environment variable
    or `gcloud run services describe`, falling back to http://localhost:8080.
    """
    env_url = os.getenv("CLOUD_RUN_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")

    if shutil.which("gcloud"):
        try:
            cmd = [
                "gcloud",
                "run",
                "services",
                "describe",
                DEFAULT_SERVICE_NAME,
                "--project",
                DEFAULT_PROJECT_ID,
                "--region",
                DEFAULT_REGION,
                "--platform",
                "managed",
                "--format=value(status.url)",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            resolved = result.stdout.strip()
            if result.returncode == 0 and resolved.startswith("http"):
                return resolved.rstrip("/")
        except Exception:
            pass

    return "http://localhost:8080"


def build_endpoint_url(base_url: str) -> str:
    """Normalize the base URL so requests target `/api/info`."""
    cleaned = base_url.strip().rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    if cleaned.endswith("/api/info"):
        return cleaned
    return f"{cleaned}/api/info"


def extract_cold_start(payload: Dict[str, Any]) -> bool:
    """
    Extract cold-start status from `/api/info` JSON payload.
    Supports both top-level `is_cold_start` / `cold_start` boolean fields
    and nested `cold_start.detected` dictionaries.
    """
    if isinstance(payload.get("is_cold_start"), bool):
        return payload["is_cold_start"]

    cold_field = payload.get("cold_start")
    if isinstance(cold_field, bool):
        return cold_field
    if isinstance(cold_field, dict):
        return bool(cold_field.get("detected", False))

    return False


def classify_release_bucket(version: str, payload: Dict[str, Any]) -> str:
    """Classify response into 'v1' (Stable) or 'v2' (Canary) bucket."""
    ver_lower = str(version).strip().lower()
    channel_lower = str(payload.get("channel", "")).strip().lower()
    is_canary = bool(payload.get("is_canary", False))

    if ver_lower.startswith("v2") or "canary" in ver_lower or "canary" in channel_lower or is_canary:
        return "v2"
    return "v1"


def send_probe(index: int, endpoint: str, timeout: float = 15.0) -> Dict[str, Any]:
    """Execute a single HTTP GET probe to `/api/info` and measure latency."""
    req = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store",
            "User-Agent": f"CloudRun-TrafficDrill/1.0 (probe={index})",
        },
        method="GET",
    )
    start_perf = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            latency_ms = (time.perf_counter() - start_perf) * 1000.0
            status_code = response.getcode()

            if status_code != 200:
                return {
                    "ok": False,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "error": f"HTTP {status_code}",
                }

            payload = json.loads(raw_body)
            version = str(payload.get("version", "unknown"))
            revision = str(
                payload.get("revision")
                or response.headers.get("X-Cloud-Run-Revision")
                or "unknown-revision"
            )
            container_id = str(
                payload.get("container_id")
                or response.headers.get("X-Container-Id")
                or "unknown-container"
            )
            cold_start = extract_cold_start(payload)
            bucket = classify_release_bucket(version, payload)

            return {
                "ok": True,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "version": version,
                "bucket": bucket,
                "revision": revision,
                "container_id": container_id,
                "cold_start": cold_start,
            }
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - start_perf) * 1000.0
        return {
            "ok": False,
            "status_code": exc.code,
            "latency_ms": latency_ms,
            "error": f"HTTPError {exc.code}: {exc.reason}",
        }
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_perf) * 1000.0
        return {
            "ok": False,
            "status_code": 0,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


def render_bar(percentage: float, width: int = 30) -> str:
    """Render an ASCII progress bar for percentage visualization."""
    clamped = max(0.0, min(100.0, percentage))
    filled = int(round((clamped / 100.0) * width))
    empty = max(0, width - filled)
    return f"[{'█' * filled}{'░' * empty}]"


def print_executive_report(
    endpoint: str,
    total_requests: int,
    wall_time_s: float,
    results: List[Dict[str, Any]],
) -> None:
    """Format and print the executive traffic distribution & telemetry report."""
    successes = [r for r in results if r.get("ok")]
    failures = [r for r in results if not r.get("ok")]

    succ_count = len(successes)
    fail_count = len(failures)
    success_rate = (succ_count / total_requests * 100.0) if total_requests else 0.0

    v1_count = sum(1 for r in successes if r.get("bucket") == "v1")
    v2_count = sum(1 for r in successes if r.get("bucket") == "v2")
    v1_pct = (v1_count / succ_count * 100.0) if succ_count else 0.0
    v2_pct = (v2_count / succ_count * 100.0) if succ_count else 0.0

    latencies = [r["latency_ms"] for r in successes]
    avg_latency = statistics.mean(latencies) if latencies else 0.0
    min_latency = min(latencies) if latencies else 0.0
    max_latency = max(latencies) if latencies else 0.0
    p95_latency = (
         sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        if latencies
        else 0.0
    )

    cold_starts = sum(1 for r in successes if r.get("cold_start"))
    warm_requests = succ_count - cold_starts
    cold_pct = (cold_starts / succ_count * 100.0) if succ_count else 0.0
    warm_pct = (warm_requests / succ_count * 100.0) if succ_count else 0.0

    revisions = collections.Counter(r["revision"] for r in successes)
    containers = collections.Counter(r["container_id"] for r in successes)

    divider = "=" * 78
    sub_divider = "-" * 78

    print(f"\n{divider}")
    print(" CLOUD RUN SERVERLESS CI/CD — EXECUTIVE TRAFFIC DRILL REPORT")
    print(divider)
    print(f" Target Endpoint     : {endpoint}")
    print(f" Wall-Clock Duration : {wall_time_s:.2f}s")
    print(sub_divider)

    print(" 1. REQUEST SUMMARY")
    print(f"    • Total Requests       : {total_requests}")
    print(f"    • Successful Responses : {succ_count} ({success_rate:.1f}%)")
    print(f"    • Failed Requests      : {fail_count}")
    print(sub_divider)

    print(" 2. CANARY TRAFFIC DISTRIBUTION (v1 Stable vs v2 Canary)")
    print(
        f"    • v1 (Stable) : {render_bar(v1_pct)} {v1_pct:6.1f}%  ({v1_count}/{succ_count} reqs)"
    )
    print(
        f"    • v2 (Canary) : {render_bar(v2_pct)} {v2_pct:6.1f}%  ({v2_count}/{succ_count} reqs)"
    )
    print(sub_divider)

    print(" 3. LATENCY TELEMETRY")
    print(f"    • Average Latency      : {avg_latency:.2f} ms")
    print(f"    • Min / P95 / Max      : {min_latency:.2f} ms / {p95_latency:.2f} ms / {max_latency:.2f} ms")
    print(sub_divider)

    print(" 4. SERVERLESS LIFECYCLE (COLD STARTS VS WARM REQUESTS)")
    print(f"    • Cold Starts Observed : {cold_starts} ({cold_pct:.1f}%)")
    print(f"    • Warm Requests        : {warm_requests} ({warm_pct:.1f}%)")
    print(f"    • Unique Containers    : {len(containers)} instance(s)")

    if revisions:
        print(sub_divider)
        print(" 5. ACTIVE CLOUD RUN REVISIONS OBSERVED")
        for rev, count in revisions.most_common():
            rev_pct = (count / succ_count * 100.0) if succ_count else 0.0
            print(f"    • {rev:<42} : {count:>4} reqs ({rev_pct:5.1f}%)")

    if failures:
        print(sub_divider)
        print(" 6. ERROR SUMMARY")
        error_counts = collections.Counter(r.get("error", "Unknown error") for r in failures)
        for err_msg, count in error_counts.most_common(5):
            print(f"    • [{count}x] {err_msg}")

    print(f"{divider}\n")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Concurrent traffic & canary distribution drill for Cloud Run (/api/info)."
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Cloud Run base URL (e.g. https://smg-serverless-app-xxx.a.run.app). "
        "Auto-detected via CLOUD_RUN_URL or gcloud if omitted.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Total number of concurrent HTTP requests to send (default: 50).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=15,
        help="Maximum number of parallel worker threads (default: 15).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    base_url = args.url or resolve_default_service_url()
    endpoint = build_endpoint_url(base_url)
    total_requests = max(1, args.count)
    max_workers = max(1, min(args.concurrency, total_requests))

    print(
        f"[*] Starting Cloud Run traffic drill: sending {total_requests} concurrent "
        f"requests (workers={max_workers}) to {endpoint} ..."
    )

    start_wall = time.perf_counter()
    results: List[Dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(send_probe, idx, endpoint)
            for idx in range(1, total_requests + 1)
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    wall_time_s = time.perf_counter() - start_wall
    print_executive_report(
        endpoint=endpoint,
        total_requests=total_requests,
        wall_time_s=wall_time_s,
        results=results,
    )

    return 0 if any(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
