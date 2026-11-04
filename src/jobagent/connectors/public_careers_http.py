"""Bounded TLS transport: pin validated IPs, prohibit redirects, never retry."""

import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
from collections.abc import Callable, Sequence
from queue import Empty, Queue
from typing import Protocol
from urllib.parse import urlsplit

from jobagent.errors import ContractValidationError, UserInterventionRequiredError
from jobagent.schemas.public_careers import PublicCareerBoard


def validate_addresses(addresses: Sequence[str]) -> None:
    if not addresses:
        raise ContractValidationError("Public source DNS returned no addresses.")
    for value in addresses:
        address = ipaddress.ip_address(value)
        mapped = getattr(address, "ipv4_mapped", None)
        if not address.is_global or (mapped is not None and not mapped.is_global):
            raise ContractValidationError("Public source resolved to a prohibited IP address.")


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    _context: ssl.SSLContext

    def connect(self) -> None:
        if not isinstance(self.timeout, (float, int)):
            raise ContractValidationError("Public connections require a finite timeout.")
        deadline = time.monotonic() + self.timeout
        # A resolver may block outside socket timeouts. A daemon resolver never
        # connects and cannot outlive the HTTP deadline by dispatching a request.
        results: Queue[object] = Queue(maxsize=1)

        def resolve() -> None:
            try:
                results.put(socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM))
            except OSError as error:
                results.put(error)

        threading.Thread(target=resolve, daemon=True).start()
        try:
            resolved = results.get(timeout=self.timeout)
        except Empty as error:
            raise TimeoutError("Public source DNS deadline exceeded.") from error
        if isinstance(resolved, OSError):
            raise resolved
        from typing import cast

        entries = cast(list[tuple[int, int, int, str, tuple[str, int]]], resolved)
        validate_addresses([str(entry[4][0]) for entry in entries])
        family, socktype, proto, _, address = entries[0]
        sock = socket.socket(family, socktype, proto)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Public source connection deadline exceeded.")
            sock.settimeout(remaining)
            sock.connect(address)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Public source TLS deadline exceeded.")
            sock.settimeout(remaining)
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class Response(Protocol):
    status: int

    def getheader(self, name: str, default: str | None = None) -> str | None: ...
    def read(self, amt: int) -> bytes: ...


class Connection(Protocol):
    def connect(self) -> None: ...
    def request(self, method: str, url: str, *, headers: dict[str, str]) -> None: ...
    def getresponse(self) -> Response: ...
    def close(self) -> None: ...


class ControlledPublicHttp:
    def __init__(self, *, connection_factory: Callable[..., Connection] | None = None) -> None:
        self.connection_factory = connection_factory or PinnedHTTPSConnection

    def get(
        self,
        board: PublicCareerBoard,
        *,
        max_bytes: int,
        timeout: int,
        dispatch: Callable[[], object],
        cancel: Callable[[], bool],
    ) -> bytes:
        # Construct the exact URL from a strict provider/board contract. No user URL,
        # environment proxy, redirect target or unbounded page link reaches sockets.
        url = urlsplit(board.api_url)
        assert url.hostname is not None
        if cancel():
            raise ContractValidationError("Public request cancelled before dispatch.")
        connection = self.connection_factory(
            url.hostname, timeout=timeout, context=ssl.create_default_context()
        )
        started = time.monotonic()

        def deadline_timeout() -> None:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Public request deadline exceeded.")
            sock = getattr(connection, "sock", None)
            if sock is not None:
                sock.settimeout(remaining)

        try:
            connection.connect()
            if cancel() or time.monotonic() - started > timeout:
                raise ContractValidationError("Public request cancelled before dispatch.")
            dispatch()
            deadline_timeout()
            path = url.path + ("?" + url.query if url.query else "")
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "CareerHarness/1.0",
                },
            )
            deadline_timeout()
            response = connection.getresponse()
            if response.status in (401, 403, 429):
                raise UserInterventionRequiredError(
                    f"Public source stopped: HTTP {response.status}."
                )
            if response.status != 200:
                raise ContractValidationError(f"Public source HTTP {response.status}; no retry.")
            if response.getheader("Content-Encoding", "identity") not in (None, "identity"):
                raise ContractValidationError("Compressed public response is unsupported.")
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > max_bytes):
                raise ContractValidationError("Public response exceeds byte limit.")
            chunks = []
            total = 0
            while True:
                if cancel() or time.monotonic() - started > timeout:
                    raise ContractValidationError("Public response cancelled or deadline exceeded.")
                deadline_timeout()
                chunk = response.read(min(65536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ContractValidationError("Public response exceeds byte limit.")
                chunks.append(chunk)
            body = b"".join(chunks)
            if length is not None and len(body) != int(length):
                raise ContractValidationError("Public response body was truncated.")
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                # Challenge pages can be HTML or plain text. Job descriptions in
                # a valid jobs payload are data and never trigger provider stops.
                context = body
            else:
                context = b""
                if isinstance(payload, dict):
                    errors = {key: payload[key] for key in ("error", "errors") if key in payload}
                    if payload.get("success") is False or not isinstance(payload.get("jobs"), list):
                        errors.update(
                            {key: payload[key] for key in ("message", "detail") if key in payload}
                        )
                    context = json.dumps(errors, ensure_ascii=False).encode("utf-8")
            lower = context.lower()
            if any(
                marker in lower
                for marker in (
                    b"captcha",
                    b"verify you are human",
                    b"access denied",
                    b"risk control",
                )
            ):
                raise UserInterventionRequiredError("Public source verification/risk control.")
            return body
        finally:
            connection.close()
