from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer

import gateway as legacy

PLATFORM_UPSTREAM = os.getenv(
    "PLATFORM_UPSTREAM",
    "http://172.17.0.1:8090",
).rstrip("/")

PLATFORM_ROUTES = {
    "/platform/health": "/health",
    "/platform/v1/catalog/github-actions": "/v1/catalog/github-actions",
    "/platform/v1/catalog/github-actions/openapi.json": "/v1/catalog/github-actions/openapi.json",
}


class H(legacy.H):
    server_version = "LexGateway/0.9.2"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        upstream_path = PLATFORM_ROUTES.get(parsed.path)

        if upstream_path is None:
            super().do_GET()
            return

        if parsed.query:
            upstream_path += "?" + parsed.query

        try:
            status, body, _ = legacy.call_json_upstream(
                PLATFORM_UPSTREAM,
                upstream_path,
                "GET",
            )
            payload = json.loads(body.decode("utf-8"))
            self.sendj(
                status,
                payload,
                {
                    "X-Platform-Proxy": "github-actions-catalog",
                    "X-Platform-Upstream": "configured",
                },
            )
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except Exception:
                payload = {
                    "error": "platform_upstream_http_error",
                    "status": error.code,
                }
            self.sendj(error.code, payload)
        except (urllib.error.URLError, TimeoutError) as error:
            self.sendj(
                502,
                {
                    "error": "platform_upstream_unavailable",
                    "detail": str(error)[:160],
                },
            )
        except Exception as error:
            self.sendj(
                500,
                {
                    "error": "platform_proxy_error",
                    "detail": error.__class__.__name__,
                },
            )


def run() -> None:
    ThreadingHTTPServer(("0.0.0.0", legacy.PORT), H).serve_forever()


if __name__ == "__main__":
    run()
