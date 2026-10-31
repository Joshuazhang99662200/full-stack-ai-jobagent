import http.client
import json
from threading import Thread


def test_http_is_read_only_scoped_and_never_serves_private_paths(tmp_path):
    from jobagent.console.server import make_server

    assets = tmp_path / "dist"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>Console</h1>", encoding="utf-8")
    (tmp_path / "private.txt").write_text("secret", encoding="utf-8")
    server = make_server(tmp_path / "absent.sqlite3", tmp_path, "CAND_DEMO", assets, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", server.server_port)
        client.request("GET", "/api/snapshot")
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["candidate_id"] == "CAND_DEMO"
        for method, path, headers, expected in [
            ("POST", "/api/snapshot", {}, 405),
            ("GET", "/api/snapshot", {"Host": "evil.test"}, 403),
            ("GET", "/api/snapshot", {"Origin": "https://evil.test"}, 403),
            ("GET", "/api/snapshot", {"Sec-Fetch-Site": "cross-site"}, 403),
            ("GET", "/../private.txt", {}, 404),
            ("GET", "/assets/%2e%2e/%2e%2e/private.txt", {}, 404),
        ]:
            client.request(method, path, headers=headers)
            response = client.getresponse()
            assert response.status == expected, (method, path, headers, response.status)
            assert b"secret" not in response.read()
        client.request("GET", "/api/definitions")
        response = client.getresponse()
        assert response.status == 200 and b"jd_text" in response.read()
        client.request("GET", "/")
        response = client.getresponse()
        assert response.status == 200 and b"Console" in response.read()
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_missing_assets_reports_build_required(tmp_path):
    from jobagent.console.server import make_server

    server = make_server(
        tmp_path / "missing.sqlite3", tmp_path, "CAND_DEMO", tmp_path / "missing-dist", port=0
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", server.server_port)
        client.request("GET", "/")
        response = client.getresponse()
        assert response.status == 503
        assert b"build" in response.read()
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
