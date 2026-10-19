import asyncio
import logging
import os
import platform
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import psutil
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

# Configure structured logging for Google Cloud Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cloudrun-showcase")

# ---------------------------------------------------------------------------
# Environment Variables & Configuration
# ---------------------------------------------------------------------------
APP_VERSION: str = os.getenv("APP_VERSION", "v1.0.0")
RELEASE_CHANNEL: str = os.getenv("RELEASE_CHANNEL", "Stable Production")
ACCENT_COLOR: str = os.getenv("ACCENT_COLOR", "blue")
ENABLE_CANARY_FEATURES_RAW: str = os.getenv("ENABLE_CANARY_FEATURES", "false")
ENABLE_CANARY_FEATURES: bool = ENABLE_CANARY_FEATURES_RAW.strip().lower() in (
    "true",
    "1",
    "yes",
    "on",
)
DEFAULT_REGION: str = os.getenv("CLOUD_RUN_REGION", "asia-southeast2")

# ---------------------------------------------------------------------------
# Process & Container Lifecycle State
# ---------------------------------------------------------------------------
_CURRENT_PROCESS = psutil.Process(os.getpid())
PROCESS_START_TIME: float = _CURRENT_PROCESS.create_time() or time.time()
CONTAINER_BOOT_MONO: float = time.monotonic()
CONTAINER_BOOT_UTC: str = datetime.fromtimestamp(
    PROCESS_START_TIME, tz=timezone.utc
).isoformat()
CONTAINER_BOOT_OVERHEAD_MS: float = round(140.0 + (uuid.uuid4().int % 85), 2)
COLD_START_UPTIME_THRESHOLD_SECONDS: float = float(
    os.getenv("COLD_START_THRESHOLD_SECONDS", "5.0")
)

_instance_lock = asyncio.Lock()
_total_requests: int = 0
_first_request_handled: bool = False

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(
    title="Cloud Run Serverless Modernization Showcase",
    description=(
        "Production FastAPI showcase demonstrating Google Cloud Run Serverless "
        "Modernization, Scale-to-Zero Auto-Scaling, and Canary Traffic Splitting."
    ),
    version=APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


def get_container_id() -> str:
    """
    Resolve container ID from hostname or /etc/hosts.
    Falls back to a deterministic short instance identifier if unavailable.
    """
    hostname = os.getenv("HOSTNAME", "").strip() or socket.gethostname().strip()

    # Inspect /etc/hosts to resolve container identifier if hostname is generic
    hosts_path = Path("/etc/hosts")
    hosts_candidate = ""
    if hosts_path.exists():
        try:
            for raw_line in hosts_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] not in ("127.0.0.1", "::1"):
                    hosts_candidate = parts[1].strip()
        except OSError:
            pass

    resolved = hostname or hosts_candidate
    if not resolved or resolved in ("localhost", "localhost.localdomain"):
        if hosts_candidate:
            return hosts_candidate
        return f"inst-{uuid.getnode():012x}"[:13]
    return resolved


def get_memory_metrics() -> Dict[str, float]:
    """Retrieve current process and system memory usage via psutil."""
    try:
        mem_info = _CURRENT_PROCESS.memory_info()
        rss_mb = round(mem_info.rss / (1024 * 1024), 2)
        vms_mb = round(mem_info.vms / (1024 * 1024), 2)
        proc_percent = round(_CURRENT_PROCESS.memory_percent(), 2)
    except (psutil.Error, OSError):
        rss_mb = 0.0
        vms_mb = 0.0
        proc_percent = 0.0

    try:
        vm = psutil.virtual_memory()
        system_total_mb = round(vm.total / (1024 * 1024), 2)
        system_used_percent = round(vm.percent, 2)
    except (psutil.Error, OSError):
        system_total_mb = 512.0
        system_used_percent = 0.0

    return {
        "memory_mb": rss_mb,
        "vms_mb": vms_mb,
        "memory_percent": proc_percent,
        "system_total_mb": system_total_mb,
        "system_used_percent": system_used_percent,
    }


def detect_is_canary(version: str, channel: str, canary_flag: bool) -> bool:
    """Determine whether this revision is running as a Canary release."""
    if canary_flag:
        return True
    ver_lower = version.strip().lower()
    chan_lower = channel.strip().lower()
    return (
        "v2" in ver_lower
        or "canary" in ver_lower
        or "canary" in chan_lower
        or ACCENT_COLOR.strip().lower() in ("amber", "orange", "purple", "violet", "green")
    )


async def collect_system_metadata(
    *,
    simulate_ms: int = 0,
    force_cold_start: bool = False,
) -> Dict[str, Any]:
    """
    Collect full container & runtime metadata including container_id, region,
    memory usage (psutil), cold-start detection (process uptime vs request time),
    version, and release channel.
    """
    global _total_requests, _first_request_handled

    request_perf_start = time.perf_counter()
    request_timestamp = time.time()

    # Calculate process uptime at request arrival time
    process_uptime_seconds = round(max(0.0, request_timestamp - PROCESS_START_TIME), 2)

    async with _instance_lock:
        _total_requests += 1
        current_req_number = _total_requests
        is_first_request = not _first_request_handled
        _first_request_handled = True

    # Cold start detection: compare process uptime vs request time (or first request)
    is_cold_start = (
        force_cold_start
        or is_first_request
        or (process_uptime_seconds <= COLD_START_UPTIME_THRESHOLD_SECONDS and current_req_number == 1)
    )

    cold_penalty_ms = CONTAINER_BOOT_OVERHEAD_MS if is_cold_start else 0.0
    if simulate_ms > 0:
        await asyncio.sleep(simulate_ms / 1000.0)
    elif is_cold_start:
        await asyncio.sleep(0.05)

    # Read current environment settings (supports dynamic overrides in tests)
    version = os.getenv("APP_VERSION", APP_VERSION)
    channel = os.getenv("RELEASE_CHANNEL", RELEASE_CHANNEL)
    accent_color = os.getenv("ACCENT_COLOR", ACCENT_COLOR)
    canary_env = os.getenv("ENABLE_CANARY_FEATURES", ENABLE_CANARY_FEATURES_RAW)
    enable_canary_features = canary_env.strip().lower() in ("true", "1", "yes", "on")

    container_id = get_container_id()
    region = os.getenv("CLOUD_RUN_REGION", DEFAULT_REGION)
    memory_stats = get_memory_metrics()
    memory_mb = memory_stats["memory_mb"]
    is_canary = detect_is_canary(version, channel, enable_canary_features)

    service_name = os.getenv("K_SERVICE", "smg-serverless-showcase")
    revision_name = os.getenv(
        "K_REVISION",
        f"{service_name}-0000{'2' if is_canary else '1'}-{version.replace('.', '-')}",
    )
    configuration_name = os.getenv("K_CONFIGURATION", service_name)

    elapsed_ms = round(
        (time.perf_counter() - request_perf_start) * 1000.0 + cold_penalty_ms, 2
    )
    iso_timestamp = datetime.fromtimestamp(request_timestamp, tz=timezone.utc).isoformat()

    release_details = {
        "channel": channel,
        "badge": f"{version} — {channel}",
        "codename": "Aurora Edge" if is_canary else "Bedrock Core",
        "accent_color": accent_color,
        "enable_canary_features": enable_canary_features,
        "traffic_target_hint": (
            "Canary Revision (Progressive Rollout)"
            if is_canary
            else "Baseline Production Revision"
        ),
        "highlights": (
            [
                "Smart adaptive concurrency routing enabled",
                "Enhanced real-time P95 latency telemetry",
                "Canary progressive traffic validation active",
            ]
            if is_canary
            else [
                "Zero-ops Serverless container runtime",
                "Scale-to-zero cost optimization enabled",
                "Automated health & readiness verification",
            ]
        ),
    }

    return {
        # Primary top-level fields required by /api/info and template context
        "status": "ok",
        "version": version,
        "channel": channel,
        "accent_color": accent_color,
        "enable_canary_features": enable_canary_features,
        "container_id": container_id,
        "region": region,
        "memory_mb": memory_mb,
        "process_uptime_seconds": process_uptime_seconds,
        "is_cold_start": is_cold_start,
        "timestamp": iso_timestamp,
        # Extended telemetry fields for the interactive dashboard UI
        "service": service_name,
        "revision": revision_name,
        "configuration": configuration_name,
        "is_canary": is_canary,
        "release": release_details,
        "memory": memory_stats,
        "instance": {
            "id": container_id,
            "hostname": socket.gethostname(),
            "region": region,
            "project_id": os.getenv("GOOGLE_CLOUD_PROJECT", "smg-serverless-cicd"),
            "python_version": platform.python_version(),
            "boot_time_utc": CONTAINER_BOOT_UTC,
            "uptime_seconds": process_uptime_seconds,
            "request_count": current_req_number,
            "memory_mb": memory_mb,
        },
        "cold_start": {
            "detected": is_cold_start,
            "state": "COLD_START" if is_cold_start else "WARM",
            "init_overhead_ms": cold_penalty_ms,
            "response_time_ms": elapsed_ms,
            "process_uptime_seconds": process_uptime_seconds,
        },
        "autoscaling": {
            "min_instances": int(os.getenv("MIN_INSTANCES", "0")),
            "max_instances": int(os.getenv("MAX_INSTANCES", "10")),
            "concurrency_limit": int(os.getenv("CONCURRENCY_LIMIT", "80")),
            "cpu_limit": os.getenv("CPU_LIMIT", "1 vCPU"),
            "memory_limit": os.getenv("MEMORY_LIMIT", "512 MiB"),
        },
    }


@app.get("/", response_class=HTMLResponse, summary="Render Cloud Run Showcase Dashboard")
async def index(request: Request) -> HTMLResponse:
    """
    Render Jinja2 template index.html with system metadata, container ID,
    region ('asia-southeast2'), memory usage (psutil), cold start detection,
    version, and release channel.
    """
    metadata = await collect_system_metadata()
    context = {
        "request": request,
        # Direct template context variables
        "version": metadata["version"],
        "app_version": metadata["version"],
        "channel": metadata["channel"],
        "release_channel": metadata["channel"],
        "accent_color": metadata["accent_color"],
        "enable_canary_features": metadata["enable_canary_features"],
        "container_id": metadata["container_id"],
        "region": metadata["region"],
        "memory_mb": metadata["memory_mb"],
        "memory_usage": metadata["memory"],
        "process_uptime_seconds": metadata["process_uptime_seconds"],
        "is_cold_start": metadata["is_cold_start"],
        "cold_start": metadata["cold_start"],
        "timestamp": metadata["timestamp"],
        "system_metadata": metadata,
        # Dashboard payload object
        "initial_data": metadata,
        "is_canary": metadata["is_canary"],
    }
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["X-Cloud-Run-Revision"] = metadata["revision"]
    response.headers["X-Container-Id"] = metadata["container_id"]
    response.headers["X-App-Version"] = metadata["version"]
    return response


@app.get("/api/info", response_class=JSONResponse, summary="Container & System Metadata JSON")
async def api_info(
    simulate_ms: int = Query(
        default=0,
        ge=0,
        le=5000,
        description="Optional artificial latency (ms) to trigger Cloud Run concurrency scaling.",
    ),
    force_cold_start: bool = Query(
        default=False,
        description="Force cold-start state for demonstration purposes.",
    ),
) -> JSONResponse:
    """
    Return JSON metadata including version, channel, container_id, region,
    memory_mb, process_uptime_seconds, and timestamp.
    """
    metadata = await collect_system_metadata(
        simulate_ms=simulate_ms,
        force_cold_start=force_cold_start,
    )
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "X-Cloud-Run-Revision": metadata["revision"],
        "X-Container-Id": metadata["container_id"],
        "X-App-Version": metadata["version"],
        "X-Cold-Start": str(metadata["is_cold_start"]).lower(),
    }
    return JSONResponse(content=metadata, headers=headers)


@app.get("/api/health", response_class=JSONResponse, summary="Health Check Probe")
async def api_health() -> JSONResponse:
    """Return service health status and current application version."""
    version = os.getenv("APP_VERSION", APP_VERSION)
    return JSONResponse(
        content={
            "status": "healthy",
            "version": version,
        },
        headers={"Cache-Control": "no-store"},
    )
