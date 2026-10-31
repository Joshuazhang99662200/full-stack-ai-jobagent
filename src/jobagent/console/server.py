"""Loopback-only GET adapter; no mutations or arbitrary private file access."""

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlsplit

from pydantic import TypeAdapter

from jobagent.console.projection import definitions, snapshot
from jobagent.schemas.candidate import CandidateId


def make_server(
    database: Path,
    workspace: Path,
    candidate_id: str,
    assets: Path,
    *,
    port: int = 8765,
) -> ThreadingHTTPServer:
    candidate_id = TypeAdapter(CandidateId).validate_python(candidate_id)
    root = assets.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(payload)

        def error_json(self, status: int, code: str) -> None:
            self.reply(
                status,
                json.dumps({"error": {"code": code}}).encode(),
                "application/json; charset=utf-8",
            )

        def allowed(self) -> bool:
            port_number = cast(ThreadingHTTPServer, self.server).server_port
            hosts = {f"127.0.0.1:{port_number}", f"localhost:{port_number}"}
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            return (
                host in hosts
                and (origin is None or origin == f"http://{host}")
                and self.headers.get("Sec-Fetch-Site") != "cross-site"
            )

        def do_POST(self) -> None:
            self.error_json(405, "read_only")

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST
        do_OPTIONS = do_POST

        def do_GET(self) -> None:
            if not self.allowed():
                self.error_json(403, "local_origin_required")
                return
            path = unquote(urlsplit(self.path).path)
            if path in {"/api/snapshot", "/api/definitions"}:
                try:
                    data = (
                        snapshot(database, workspace, candidate_id).model_dump(mode="json")
                        if path == "/api/snapshot"
                        else definitions()
                    )
                    self.reply(
                        200,
                        json.dumps(data, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8",
                    )
                except (OSError, ValueError):
                    self.error_json(503, "source_unavailable")
                return
            if path == "/":
                target = root / "index.html"
            elif path.startswith("/assets/") and ".." not in path.split("/"):
                target = (root / path.lstrip("/")).resolve()
            else:
                self.error_json(404, "not_found")
                return
            if not target.is_relative_to(root) or target.is_symlink():
                self.error_json(404, "not_found")
                return
            try:
                content = target.read_bytes()
            except OSError:
                self.error_json(
                    503 if path == "/" else 404,
                    "frontend_build_required" if path == "/" else "not_found",
                )
                return
            self.reply(
                200, content, mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
