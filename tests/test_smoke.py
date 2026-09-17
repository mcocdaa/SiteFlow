import re

from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_gallery_empty_state() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SiteFlow" in response.text
    assert "还没有作品" in response.text


def test_login_reaches_admin() -> None:
    with TestClient(app) as client:
        page = client.get("/login")
        match = re.search(r'name="csrf" value="([^"]+)"', page.text)
        assert match is not None
        response = client.post(
            "/login",
            data={"password": app.state.config.password, "csrf": match.group(1)},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin"
        admin = client.get("/admin")
        assert admin.status_code == 200
        assert "退出登录" in admin.text
