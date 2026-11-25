import hashlib
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import templating
from app.main import app
from app.templating import static_url
from tests.test_apps import create_app
from tests.test_flow import auth_headers, login

VERSIONED_RE = re.compile(r"^/static/.+\?v=[0-9a-f]{8}$")


def _all_static_refs(html: str) -> list[str]:
    return re.findall(r'(?:href|src)="(/static/[^"]+)"', html)


def test_static_url_normalization_hash_fallback_and_reload(tmp_path: Path, monkeypatch) -> None:
    css_file = templating.STATIC_DIR / "css" / "app.css"
    expected_digest = hashlib.sha256(css_file.read_bytes()).hexdigest()[:8]
    expected_url = f"/static/css/app.css?v={expected_digest}"

    assert static_url("css/app.css") == expected_url
    assert static_url("/css/app.css") == expected_url
    assert static_url("/static/css/app.css") == expected_url
    assert static_url("static/css/app.css") == expected_url
    assert static_url("/static/css/app.css?v=old00000") == expected_url
    assert VERSIONED_RE.match(expected_url)

    assert static_url("does/not/exist.css") == "/static/does/not/exist.css"
    assert static_url("/static/does/not/exist.css") == "/static/does/not/exist.css"
    assert static_url("../main.py") == "/static/../main.py"
    assert static_url("") == "/static/"

    monkeypatch.setattr(templating, "STATIC_DIR", tmp_path)
    sample = tmp_path / "js" / "demo.js"
    sample.parent.mkdir(parents=True)
    sample.write_text("const v = 1;\n", encoding="utf-8")
    first = static_url("js/demo.js")
    assert VERSIONED_RE.match(first)

    sample.write_text("const v = 22;\n", encoding="utf-8")
    stat = sample.stat()
    os.utime(sample, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = static_url("js/demo.js")
    assert VERSIONED_RE.match(second)
    assert second != first


def test_html_pages_emit_versioned_static_assets_and_cache_headers() -> None:
    expected_css = static_url("css/app.css")
    expected_i18n = static_url("js/i18n.js")
    expected_katex_css = static_url("vendor/katex/katex.min.css")
    expected_katex_js = static_url("vendor/katex/katex.min.js")
    expected_blog_post_js = static_url("js/blog_post.js")
    expected_mascot_css = static_url("/static/css/blog_ext_mascot.css")
    expected_mascot_js = static_url("/static/js/blog_ext_mascot.js")

    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "缓存测试空间").json()["project"]
        resume = create_app(client, csrf, "resume", "缓存测试简历").json()["project"]
        blog = create_app(client, csrf, "blog", "缓存测试博客").json()["project"]

        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/extensions/mascot/install",
                json={"enabled": True, "config": {}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/posts",
                json={
                    "title": "缓存测试文章",
                    "slug": "cache-post",
                    "summary": "公式 $E=mc^2$",
                    "body": "# 标题\n\n## 小节\n\n$$a^2+b^2=c^2$$\n",
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        pages = [
            "/",
            "/login",
            "/admin",
            f"/admin/projects/{space['id']}",
            f"/admin/projects/{resume['id']}",
            f"/admin/projects/{blog['id']}",
            f"/admin/projects/{blog['id']}/posts/new",
            f"/projects/{space['slug']}/",
            f"/projects/{resume['slug']}/",
            f"/projects/{blog['slug']}/",
            f"/projects/{blog['slug']}/posts/cache-post",
        ]
        for url in pages:
            resp = client.get(url)
            assert resp.status_code == 200, url
            assert f'href="{expected_css}"' in resp.text, url
            assert f'src="{expected_i18n}"' in resp.text, url
            refs = _all_static_refs(resp.text)
            assert refs, url
            for ref in refs:
                assert VERSIONED_RE.match(ref), f"unversioned asset {ref} on {url}"

        post_html = client.get(f"/projects/{blog['slug']}/posts/cache-post").text
        assert f'href="{expected_katex_css}"' in post_html
        assert f'src="{expected_katex_js}"' in post_html
        assert f'src="{expected_blog_post_js}"' in post_html
        assert f'href="{expected_mascot_css}"' in post_html
        assert f'src="{expected_mascot_js}"' in post_html

        assert (
            client.patch(
                f"/api/admin/projects/{space['id']}",
                json={"password": "gate-password-123"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        client.cookies.clear()
        gate_resp = client.get(f"/projects/{space['slug']}/")
        assert gate_resp.status_code == 200
        assert f'href="{expected_css}"' in gate_resp.text
        assert f'src="{expected_i18n}"' in gate_resp.text
        for ref in _all_static_refs(gate_resp.text):
            assert VERSIONED_RE.match(ref)

        for method in ("get", "head"):
            versioned_resp = getattr(client, method)(expected_css)
            assert versioned_resp.status_code == 200
            assert versioned_resp.headers["cache-control"] == "public, max-age=31536000, immutable"
            assert versioned_resp.headers["x-content-type-options"] == "nosniff"
            assert versioned_resp.headers["x-frame-options"] == "DENY"
            assert versioned_resp.headers["referrer-policy"] == "same-origin"

            unversioned_resp = getattr(client, method)("/static/css/app.css")
            assert unversioned_resp.status_code == 200
            assert unversioned_resp.headers["cache-control"] == "no-cache"
            assert unversioned_resp.headers["x-content-type-options"] == "nosniff"

        missing_resp = client.get("/static/css/does-not-exist.css?v=12345678")
        assert missing_resp.status_code == 404
        assert missing_resp.headers["cache-control"] == "no-cache"
