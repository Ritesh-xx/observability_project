import os
import time
import random
from functools import wraps

import psycopg2
import redis
import requests

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

from opentelemetry import trace


app = Flask(__name__)


# ============================================================
# Configuration
# ============================================================

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "appdb")
DB_USER = os.getenv("DB_USER", "appuser")
DB_PASSWORD = os.getenv("DB_PASSWORD", "apppass")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

EXTERNAL_API_URL = os.getenv(
    "EXTERNAL_API_URL",
    "http://external-api:8081",
)


# ============================================================
# Prometheus metrics
# ============================================================

REQS = Counter(
    "app_http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)

REQ_LATENCY = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "route"],
)

DB_ERRORS = Counter(
    "app_db_errors_total",
    "Database errors",
)

DB_LATENCY = Histogram(
    "app_db_query_duration_seconds",
    "Database query duration",
)

REDIS_ERRORS = Counter(
    "app_redis_errors_total",
    "Redis errors",
)

REDIS_LATENCY = Histogram(
    "app_redis_operation_duration_seconds",
    "Redis operation duration",
)

EXT_ERRORS = Counter(
    "app_external_api_errors_total",
    "External API errors",
)

EXT_LATENCY = Histogram(
    "app_external_api_duration_seconds",
    "External API request duration",
)

INFLIGHT = Gauge(
    "app_inflight_requests",
    "In-flight requests",
)


# ============================================================
# OpenTelemetry helpers
# ============================================================

def get_trace_context():
    """
    Get the trace ID and span ID associated with the
    current OpenTelemetry request.

    If there is no active trace, return zeros.
    """

    span = trace.get_current_span()
    span_context = span.get_span_context()

    if not span_context.is_valid:
        return "00000000000000000000000000000000", "0000000000000000"

    trace_id = format(span_context.trace_id, "032x")
    span_id = format(span_context.span_id, "016x")

    return trace_id, span_id


# ============================================================
# Database
# ============================================================

def db_conn():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=2,
    )


# ============================================================
# Redis
# ============================================================

def get_redis():
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        socket_connect_timeout=2,
        decode_responses=True,
    )


# ============================================================
# Request instrumentation
# ============================================================

def instrument(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        route = request.path
        start = time.time()

        INFLIGHT.inc()

        try:
            result = fn(*args, **kwargs)

            return result

        finally:
            duration = time.time() - start

            REQ_LATENCY.labels(
                request.method,
                route,
            ).observe(duration)

            INFLIGHT.dec()

    return wrapper


# ============================================================
# Database retry helper
# ============================================================

def retry_db(fn, attempts=3):
    last = None

    for _ in range(attempts):
        try:
            return fn()

        except Exception as exc:
            last = exc
            time.sleep(0.1)

    raise last


# ============================================================
# Routes
# ============================================================

@app.route("/")
@instrument
def home():
    return jsonify({
        "service": "observability-lab",
        "status": "ok",
    }), 200


@app.route("/health")
def health():
    return jsonify({
        "status": "ok"
    })


@app.route("/ready")
def ready():
    checks = {}

    # Database health
    try:
        conn = db_conn()
        conn.close()

        checks["database"] = "ok"

    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    # Redis health
    try:
        r = get_redis()
        r.ping()

        checks["redis"] = "ok"

    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"

    ok = all(
        value == "ok"
        for value in checks.values()
    )

    return jsonify({
        "status": "ready" if ok else "not_ready",
        "checks": checks,
    }), (200 if ok else 503)


@app.route("/users")
@instrument
def users():
    start = time.time()

    try:
        conn = db_conn()
        cur = conn.cursor()

        cur.execute(
            "SELECT id, name FROM users ORDER BY id LIMIT 20"
        )

        rows = cur.fetchall()

        cur.close()
        conn.close()

        DB_LATENCY.observe(
            time.time() - start
        )

        return jsonify([
            {
                "id": row[0],
                "name": row[1],
            }
            for row in rows
        ]), 200

    except Exception:
        DB_ERRORS.inc()
        raise


@app.route("/cache/<key>")
@instrument
def cache_get(key):
    start = time.time()

    try:
        r = get_redis()

        value = r.get(key)

        REDIS_LATENCY.observe(
            time.time() - start
        )

        return jsonify({
            "key": key,
            "value": value,
        }), 200

    except Exception:
        REDIS_ERRORS.inc()
        raise


@app.route("/external")
@instrument
def external():
    start = time.time()

    try:
        timeout = float(
            request.args.get(
                "timeout",
                "2",
            )
        )

        response = requests.get(
            f"{EXTERNAL_API_URL}/data",
            timeout=timeout,
        )

        EXT_LATENCY.observe(
            time.time() - start
        )

        if response.status_code >= 500:
            EXT_ERRORS.inc()

        return jsonify({
            "upstream_status": response.status_code,
            "data": response.json(),
        }), response.status_code

    except Exception as exc:
        EXT_ERRORS.inc()

        EXT_LATENCY.observe(
            time.time() - start
        )

        return jsonify({
            "error": "external dependency failed",
            "detail": str(exc),
        }), 502


@app.route("/work")
@instrument
def work():
    delay = float(
        request.args.get(
            "delay",
            "0",
        )
    )

    if delay > 0:
        time.sleep(
            min(delay, 30)
        )

    return jsonify({
        "worked": True,
        "delay": delay,
    })


@app.route("/error")
@instrument
def error():
    return jsonify({
        "error": "intentional application error"
    }), 500


@app.route("/cpu")
@instrument
def cpu():
    seconds = min(
        float(
            request.args.get(
                "seconds",
                "5",
            )
        ),
        30,
    )

    end = time.time() + seconds
    x = 0

    while time.time() < end:
        x = (x * 33 + 7) % 10000019

    return jsonify({
        "cpu_burned_seconds": seconds,
        "result": x,
    })


@app.route("/memory")
@instrument
def memory():
    mb = min(
        int(
            request.args.get(
                "mb",
                "100",
            )
        ),
        512,
    )

    duration = min(
        int(
            request.args.get(
                "seconds",
                "30",
            )
        ),
        120,
    )

    blob = bytearray(
        mb * 1024 * 1024
    )

    for i in range(
        0,
        len(blob),
        4096,
    ):
        blob[i] = random.randint(
            0,
            255,
        )

    time.sleep(duration)

    return jsonify({
        "allocated_mb": mb,
        "seconds": duration,
    })


@app.route("/db-slow")
@instrument
def db_slow():
    seconds = min(
        float(
            request.args.get(
                "seconds",
                "5",
            )
        ),
        30,
    )

    try:
        conn = db_conn()
        cur = conn.cursor()

        start = time.time()

        cur.execute(
            "SELECT pg_sleep(%s)",
            (seconds,),
        )

        cur.close()
        conn.close()

        DB_LATENCY.observe(
            time.time() - start
        )

        return jsonify({
            "slept_seconds": seconds,
        }), 200

    except Exception:
        DB_ERRORS.inc()

        return jsonify({
            "error": "database failure"
        }), 503


@app.route("/metrics")
def metrics():
    return (
        generate_latest(),
        200,
        {
            "Content-Type": CONTENT_TYPE_LATEST
        },
    )


# ============================================================
# Error handler
# ============================================================

@app.errorhandler(Exception)
def handle_error(err):
    trace_id, span_id = get_trace_context()

    if isinstance(err, HTTPException):

        print(
            f"LEVEL=ERROR "
            f"TRACE_ID={trace_id} "
            f"SPAN_ID={span_id} "
            f"ERROR_TYPE={type(err).__name__} "
            f"METHOD={request.method} "
            f"PATH={request.path} "
            f"STATUS={err.code} "
            f"MESSAGE={err.description}",
            flush=True,
        )

        return jsonify({
            "error": err.name,
            "message": err.description,
        }), err.code

    import traceback

    traceback.print_exc()

    print(
        f"LEVEL=ERROR "
        f"TRACE_ID={trace_id} "
        f"SPAN_ID={span_id} "
        f"ERROR_TYPE={type(err).__name__} "
        f"METHOD={request.method} "
        f"PATH={request.path} "
        f"STATUS=500 "
        f"MESSAGE={str(err)}",
        flush=True,
    )

    return jsonify({
        "error": "internal server error",
        "type": type(err).__name__,
        "message": str(err),
    }), 500


# ============================================================
# Request metrics
# ============================================================

@app.after_request
def record_request(response):
    REQS.labels(
        method=request.method,
        route=request.path,
        status=response.status_code,
    ).inc()

    return response


# ============================================================
# Request logging with OpenTelemetry correlation
# ============================================================

@app.after_request
def log_request(response):
    trace_id, span_id = get_trace_context()

    print(
        f"LEVEL=INFO "
        f"TRACE_ID={trace_id} "
        f"SPAN_ID={span_id} "
        f"IP={request.remote_addr} "
        f"METHOD={request.method} "
        f"PATH={request.path} "
        f"STATUS={response.status_code} "
        f"USER_AGENT={request.headers.get('User-Agent')}",
        flush=True,
    )

    return response


# ============================================================
# Application startup
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
    )
