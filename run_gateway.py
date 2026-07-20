from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer

import gateway

MEMORY_UPSTREAM = os.getenv("LEX_MEMORY_UPSTREAM", "").strip().rstrip("/")
_original_do_get = gateway.H.do_GET


def _memory_status(handler: gateway.H, parsed: urllib.parse.ParseResult) -> None:
    if not MEMORY_UPSTREAM:
        handler.sendj(503, {"error": "memory_upstream_not_configured"})
        return

    try:
        status, body, _ = gateway.call_json_upstream(
            MEMORY_UPSTREAM,
            "/v1/memory/status",
            "GET",
        )
        data = json.loads(body.decode())
        data["access_tier"] = "status_read_only"
        data["human_review_required"] = True
        data["secret_returned"] = False
        handler.sendj(status, data)
    except urllib.error.HTTPError as error:
        try:
            data = json.loads(error.read().decode())
        except Exception:
            data = {
                "error": "memory_upstream_http_error",
                "status": error.code,
            }
        handler.sendj(error.code, data)
    except (urllib.error.URLError, TimeoutError) as error:
        handler.sendj(
            502,
            {
                "error": "memory_upstream_unavailable",
                "detail": str(error)[:160],
            },
        )
    except Exception as error:
        handler.sendj(
            500,
            {
                "error": "gateway_error",
                "detail": error.__class__.__name__,
            },
        )


def _do_get_with_memory(handler: gateway.H) -> None:
    parsed = urllib.parse.urlparse(handler.path)
    if parsed.path == "/v1/memory/status":
        _memory_status(handler, parsed)
        return
    _original_do_get(handler)


gateway.H.do_GET = _do_get_with_memory


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", gateway.PORT), gateway.H).serve_forever()


if __name__ == "__main__":
    main()
