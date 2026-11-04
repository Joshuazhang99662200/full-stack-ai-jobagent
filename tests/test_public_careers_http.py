import pytest

from jobagent.connectors.public_careers_http import ControlledPublicHttp, validate_addresses
from jobagent.errors import ContractValidationError, UserInterventionRequiredError
from jobagent.schemas.public_careers import PublicCareerBoard


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["::1"], ["169.254.169.254"], ["::ffff:127.0.0.1"], ["8.8.8.8", "10.0.0.1"]],
)
def test_all_resolved_ips_must_be_public(addresses):
    with pytest.raises(ContractValidationError):
        validate_addresses(addresses)


def test_dns_checks_are_bound_to_connect_ip(monkeypatch):
    import socket

    from jobagent.connectors.public_careers_http import PinnedHTTPSConnection

    connected = []

    class FakeSocket:
        def settimeout(self, value):
            pass

        def connect(self, address):
            connected.append(address)

        def close(self):
            pass

    class TLS:
        def wrap_socket(self, sock, server_hostname):
            assert server_hostname == "boards-api.greenhouse.io"
            return sock

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket())
    connection = PinnedHTTPSConnection("boards-api.greenhouse.io", timeout=2)
    connection._context = TLS()
    connection.connect()
    assert connected == [("8.8.8.8", 443)]


class Reply:
    def __init__(self, status=200, body=b'{"jobs":[]}'):
        self.status, self.body = status, body

    def getheader(self, name, default=None):
        return default

    def read(self, limit):
        result = self.body[:limit]
        self.body = self.body[limit:]
        return result


def transport(status=200, body=b'{"jobs":[]}'):
    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Reply(status, body)

        def close(self):
            pass

    return ControlledPublicHttp(connection_factory=Connection)


@pytest.mark.parametrize("status", [403, 429])
def test_stops_and_never_retries(status):
    debits = []
    with pytest.raises(UserInterventionRequiredError):
        transport(status).get(
            PublicCareerBoard(provider="ashby", board="synthetic", company="X"),
            max_bytes=100,
            timeout=1,
            dispatch=lambda: debits.append(1),
            cancel=lambda: False,
        )
    assert debits == [1]


@pytest.mark.parametrize(
    "status,body", [(302, b""), (200, b"x" * 101), (200, b"<html>captcha</html>")]
)
def test_redirect_size_and_gate_are_not_zero_results(status, body):
    with pytest.raises((ContractValidationError, UserInterventionRequiredError)):
        transport(status, body).get(
            PublicCareerBoard(provider="ashby", board="synthetic", company="X"),
            max_bytes=100,
            timeout=1,
            dispatch=lambda: None,
            cancel=lambda: False,
        )


def test_cancelled_before_dispatch_spends_nothing():
    debits = []
    with pytest.raises(ContractValidationError):
        transport().get(
            PublicCareerBoard(provider="ashby", board="synthetic", company="X"),
            max_bytes=100,
            timeout=1,
            dispatch=lambda: debits.append(1),
            cancel=lambda: True,
        )
    assert debits == []


def test_success_receipt_is_exactly_one_and_body_is_bounded():
    debits = []
    result = transport().get(
        PublicCareerBoard(provider="ashby", board="synthetic", company="X"),
        max_bytes=100,
        timeout=1,
        dispatch=lambda: debits.append(1),
        cancel=lambda: False,
    )
    assert result == b'{"jobs":[]}' and debits == [1]


def test_normal_job_description_gate_words_are_not_platform_controls():
    body = b'{"jobs":[{"descriptionPlain":"Build risk control and CAPTCHA systems"}]}'
    result = transport(body=body).get(
        PublicCareerBoard(provider="ashby", board="synthetic", company="X"),
        max_bytes=1000,
        timeout=1,
        dispatch=lambda: None,
        cancel=lambda: False,
    )
    assert result == body


@pytest.mark.parametrize(
    "body",
    [
        b"<html>CAPTCHA verification required</html>",
        b'{"error":"CAPTCHA verification required"}',
        b'{"success":false,"message":"risk control"}',
    ],
)
def test_challenge_pages_and_top_level_error_context_still_stop(body):
    with pytest.raises(UserInterventionRequiredError):
        transport(body=body).get(
            PublicCareerBoard(provider="ashby", board="synthetic", company="X"),
            max_bytes=1000,
            timeout=1,
            dispatch=lambda: None,
            cancel=lambda: False,
        )


def test_dns_resolution_has_a_deadline(monkeypatch):
    import socket
    import time

    from jobagent.connectors.public_careers_http import PinnedHTTPSConnection

    def slow(*args, **kwargs):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", slow)
    connection = PinnedHTTPSConnection("boards-api.greenhouse.io", timeout=0.01)
    started = time.monotonic()
    with pytest.raises((TimeoutError, ContractValidationError)):
        connection.connect()
    assert time.monotonic() - started < 0.15
