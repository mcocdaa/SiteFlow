import io
import re
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.og import parse_og
from tests.test_flow import ORIGIN, login, make_zip, upload


def test_symlink_zip_rejected() -> None:
    info = zipfile.ZipInfo("link")
    info.external_attr = 0o120777 << 16
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("index.html", b"ok")
        archive.writestr(info, "target")
    with TestClient(app) as client:
        csrf = login(client)
        response = upload(client, csrf, "symlink.zip", buffer.getvalue())
    assert response.status_code == 422


def test_extract_size_limit(monkeypatch) -> None:
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.config, "extract_limit", 1024)
        csrf = login(client)
        response = upload(client, csrf, "bomb.zip", make_zip({"index.html": b"x" * 5000}))
    assert response.status_code == 422


def test_parse_og_metadata() -> None:
    html = (
        b"<html><head><title>Fallback</title>"
        b'<meta property="og:title" content="OG Title">'
        b'<meta property="og:description" content="OG Desc">'
        b'<meta property="og:image" content="https://example.com/i.png">'
        b"</head></html>"
    )
    og = parse_og(html, "https://example.com")
    assert og is not None
    assert og.title == "OG Title"
    assert og.description == "OG Desc"
    assert og.image_url == "https://example.com/i.png"

    plain = parse_og(b"<title>Only</title>", "https://example.com")
    assert plain is not None
    assert plain.title == "Only"


def test_login_rate_limit() -> None:
    with TestClient(app) as client:
        for _ in range(5):
            page = client.get("/login")
            token = re.search(r'name="csrf" value="([^"]+)"', page.text)
            assert token is not None
            client.post(
                "/login",
                data={"password": "wrong", "csrf": token.group(1)},
                headers=ORIGIN,
            )
        page = client.get("/login")
        token = re.search(r'name="csrf" value="([^"]+)"', page.text)
        assert token is not None
        response = client.post(
            "/login",
            data={"password": "test-password", "csrf": token.group(1)},
            headers=ORIGIN,
        )
    assert response.status_code == 429


def test_password_change_invalidates_session(monkeypatch) -> None:
    with TestClient(app) as client:
        login(client)
        assert client.get("/admin", follow_redirects=False).status_code == 200

        monkeypatch.setattr(app.state.config, "password", "rotated-pass")
        assert client.get("/admin", follow_redirects=False).status_code == 303

        page = client.get("/login")
        token = re.search(r'name="csrf" value="([^"]+)"', page.text)
        assert token is not None
        response = client.post(
            "/login",
            data={"password": "rotated-pass", "csrf": token.group(1)},
            headers=ORIGIN,
            follow_redirects=False,
        )
    assert response.status_code == 303
