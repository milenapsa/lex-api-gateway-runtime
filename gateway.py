from __future__ import annotations

import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.getenv("PORT", "8090"))
UPSTREAM = os.getenv(
    "LEX_UPSTREAM",
    "http://homosapiens-lex-search-core-v51:8080",
).rstrip("/")
PROCESS_UPSTREAM = os.getenv("LEX_PROCESS_UPSTREAM", "").strip().rstrip("/")
DEMO_LIMIT = int(os.getenv("LEX_DEMO_REQUESTS_PER_HOUR", "20"))
COMM_LIMIT = int(os.getenv("LEX_COMMERCIAL_REQUESTS_PER_MINUTE", "120"))
API_KEY = os.getenv("LEX_API_KEY", "").strip()
buckets = defaultdict(deque)

DATAJUD_PROCESS_PATH = re.compile(
    r"^/v1/datajud/processos/(?P<numero_cnj>[0-9.\-]{20,25})(?:/timeline)?$"
)


def allow(key: str, cap: int, window: int) -> tuple[bool, int, int]:
    now = time.monotonic()
    queue = buckets[key]
    while queue and queue[0] <= now - window:
        queue.popleft()
    if len(queue) >= cap:
        retry = max(1, int(window - (now - queue[0])))
        return False, 0, retry
    queue.append(now)
    return True, cap - len(queue), 0


def call_json_upstream(
    base_url: str,
    path: str,
    method: str,
    body: bytes | None = None,
) -> tuple[int, bytes, dict]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "LexGateway/0.9",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url + path,
        data=body,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, response.read(), dict(response.headers)


class H(BaseHTTPRequestHandler):
    server_version = "LexGateway/0.9"

    def sendj(self, status: int, obj: dict, headers: dict | None = None) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(data)

    def ip(self) -> str:
        forwarded = self.headers.get(
            "X-Forwarded-For",
            self.client_address[0],
        )
        return forwarded.split(",")[0].strip()

    def key(self) -> str:
        key = self.headers.get("X-API-Key", "").strip()
        if key:
            return key
        authorization = self.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return ""

    def require_commercial_auth(self) -> tuple[bool, int]:
        if not API_KEY:
            self.sendj(503, {"error": "commercial_auth_not_configured"})
            return False, 0

        presented = self.key()
        if not presented or not hmac.compare_digest(presented, API_KEY):
            self.sendj(401, {"error": "invalid_api_key"})
            return False, 0

        ok, remaining, retry = allow("commercial", COMM_LIMIT, 60)
        if not ok:
            self.sendj(
                429,
                {
                    "error": "commercial_rate_limit_exceeded",
                    "retry_after_seconds": retry,
                },
                {"Retry-After": retry},
            )
            return False, 0
        return True, remaining

    def read(self) -> bytes:
        size = int(self.headers.get("Content-Length", "0") or 0)
        if size > 64000:
            raise ValueError("payload_too_large")
        return self.rfile.read(size)

    def proxy_datajud_get(self, parsed: urllib.parse.ParseResult) -> None:
        if not PROCESS_UPSTREAM:
            self.sendj(503, {"error": "process_upstream_not_configured"})
            return

        authorized, remaining = self.require_commercial_auth()
        if not authorized:
            return

        target = parsed.path
        if parsed.query:
            target += "?" + parsed.query

        try:
            status, body, _ = call_json_upstream(
                PROCESS_UPSTREAM,
                target,
                "GET",
            )
            data = json.loads(body.decode())
            data["access_tier"] = "commercial_pilot"
            self.sendj(
                status,
                data,
                {
                    "X-RateLimit-Limit": COMM_LIMIT,
                    "X-RateLimit-Remaining": remaining,
                },
            )
        except urllib.error.HTTPError as error:
            try:
                data = json.loads(error.read().decode())
            except Exception:
                data = {
                    "error": "process_upstream_http_error",
                    "status": error.code,
                }
            self.sendj(error.code, data)
        except (urllib.error.URLError, TimeoutError) as error:
            self.sendj(
                502,
                {
                    "error": "process_upstream_unavailable",
                    "detail": str(error)[:160],
                },
            )
        except Exception as error:
            self.sendj(
                500,
                {
                    "error": "gateway_error",
                    "detail": error.__class__.__name__,
                },
            )

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self.sendj(
                200,
                {
                    "status": "ok",
                    "service": "lex-api-gateway",
                    "version": "0.9.0-contract",
                    "demo_limit_per_hour": DEMO_LIMIT,
                    "commercial_limit_per_minute": COMM_LIMIT,
                    "commercial_auth": (
                        "configured" if API_KEY else "not_configured"
                    ),
                    "process_upstream": (
                        "configured"
                        if PROCESS_UPSTREAM
                        else "not_configured"
                    ),
                    "secret_returned": False,
                },
            )
            return

        if path == "/v1/readiness":
            self.sendj(
                200,
                {
                    "status": (
                        "ready"
                        if API_KEY and PROCESS_UPSTREAM
                        else "ready_with_limits"
                    ),
                    "demo": True,
                    "commercial": bool(API_KEY),
                    "search_upstream": UPSTREAM,
                    "process_upstream_configured": bool(PROCESS_UPSTREAM),
                    "human_review_required": True,
                    "no_invention_policy": True,
                },
            )
            return

        if path == "/v1/datajud/health":
            self.proxy_datajud_get(parsed)
            return

        if DATAJUD_PROCESS_PATH.fullmatch(path):
            self.proxy_datajud_get(parsed)
            return

        self.sendj(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        demo = path == "/v1/search/demo"
        commercial = path in {
            "/v1/search",
            "/v1/search/global",
            "/v1/search/legislacao",
            "/v1/search/datasets",
        }
        if not demo and not commercial:
            self.sendj(404, {"error": "not_found"})
            return

        if demo:
            ok, remaining, retry = allow(
                "demo:" + self.ip(),
                DEMO_LIMIT,
                3600,
            )
            if not ok:
                self.sendj(
                    429,
                    {
                        "error": "demo_rate_limit_exceeded",
                        "retry_after_seconds": retry,
                    },
                    {"Retry-After": retry},
                )
                return
            target = "/v1/search"
            tier = "public_demo"
            cap = 5
        else:
            authorized, remaining = self.require_commercial_auth()
            if not authorized:
                return
            target = path
            tier = "commercial_pilot"
            cap = 20

        try:
            raw = self.read()
            payload = json.loads(raw or b"{}")
            query = str(
                payload.get("query") or payload.get("q") or ""
            ).strip()
            if not query:
                self.sendj(422, {"error": "query_required"})
                return

            payload["limit"] = min(
                max(1, int(payload.get("limit", 10))),
                cap,
            )
            status, body, _ = call_json_upstream(
                UPSTREAM,
                target,
                "POST",
                json.dumps(payload, ensure_ascii=False).encode(),
            )
            data = json.loads(body.decode())
            data["access_tier"] = tier
            self.sendj(
                status,
                data,
                {
                    "X-RateLimit-Limit": (
                        DEMO_LIMIT if demo else COMM_LIMIT
                    ),
                    "X-RateLimit-Remaining": remaining,
                },
            )
        except ValueError as error:
            self.sendj(400, {"error": str(error)})
        except urllib.error.HTTPError as error:
            try:
                data = json.loads(error.read().decode())
            except Exception:
                data = {
                    "error": "search_upstream_http_error",
                    "status": error.code,
                }
            self.sendj(error.code, data)
        except (urllib.error.URLError, TimeoutError) as error:
            self.sendj(
                502,
                {
                    "error": "upstream_unavailable",
                    "detail": str(error)[:160],
                },
            )
        except Exception as error:
            self.sendj(
                500,
                {
                    "error": "gateway_error",
                    "detail": error.__class__.__name__,
                },
            )

    def log_message(self, fmt: str, *args: object) -> None:
        print(
            json.dumps(
                {
                    "time": time.time(),
                    "client": self.ip(),
                    "method": self.command,
                    "path": urllib.parse.urlparse(self.path).path,
                    "message": fmt % args,
                }
            ),
            flush=True,
        )


ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
