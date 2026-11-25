import json
import re
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

from app import auth
from app.main import app
from app.plugins.resume.plugin import validate_content as validate_resume
from tests.test_apps import create_app
from tests.test_flow import ORIGIN, auth_headers, login, make_png, make_zip
from tests.test_mascot_chat import _patch_upstream


def test_deploy_preserves_visibility_for_hidden_and_nested_projects() -> None:
    token = app.state.config.api_token
    bearer = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as admin_client, TestClient(app) as anon_client:
        csrf = login(admin_client)

        default_new = admin_client.put(
            "/api/admin/projects/default-vis/deploy",
            files={"file": ("index.html", b"<h1>default</h1>", "text/html")},
            headers=bearer,
        )
        assert default_new.status_code == 200
        assert default_new.json()["project"]["visible"] is True
        assert anon_client.get("/projects/default-vis/index.html").status_code == 200

        hidden_new = admin_client.put(
            "/api/admin/projects/born-hidden/deploy",
            files={"file": ("index.html", b"<h1>hidden-v1</h1>", "text/html")},
            data={"visible": "false"},
            headers=bearer,
        )
        assert hidden_new.status_code == 200
        assert hidden_new.json()["project"]["visible"] is False
        assert anon_client.get("/projects/born-hidden/index.html").status_code == 404

        redeploy_omit = admin_client.put(
            "/api/admin/projects/born-hidden/deploy",
            files={"file": ("index.html", b"<h1>hidden-v2</h1>", "text/html")},
            headers=bearer,
        )
        assert redeploy_omit.status_code == 200
        assert redeploy_omit.json()["project"]["visible"] is False
        assert anon_client.get("/projects/born-hidden/index.html").status_code == 404
        assert "born-hidden" not in anon_client.get("/").text
        assert all(item["slug"] != "born-hidden" for item in anon_client.get("/api/search").json())

        redeploy_alias = admin_client.post(
            "/api/deploy/born-hidden",
            files={"file": ("index.html", b"<h1>hidden-v3</h1>", "text/html")},
            headers=bearer,
        )
        assert redeploy_alias.status_code == 200
        assert redeploy_alias.json()["project"]["visible"] is False
        assert anon_client.get("/projects/born-hidden/index.html").status_code == 404

        redeploy_show = admin_client.put(
            "/api/admin/projects/born-hidden/deploy",
            files={"file": ("index.html", b"<h1>now-public</h1>", "text/html")},
            data={"visible": "true"},
            headers=bearer,
        )
        assert redeploy_show.status_code == 200
        assert redeploy_show.json()["project"]["visible"] is True
        assert anon_client.get("/projects/born-hidden/index.html").status_code == 200

        redeploy_hide = admin_client.put(
            "/api/admin/projects/born-hidden/deploy",
            files={"file": ("index.html", b"<h1>hidden-again</h1>", "text/html")},
            data={"visible": "false"},
            headers=bearer,
        )
        assert redeploy_hide.status_code == 200
        assert redeploy_hide.json()["project"]["visible"] is False
        assert anon_client.get("/projects/born-hidden/index.html").status_code == 404

        visible_space = create_app(admin_client, csrf, "space", "可见父空间").json()["project"]
        hidden_space = create_app(admin_client, csrf, "space", "隐藏父空间").json()["project"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{hidden_space['id']}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        child_in_vis = admin_client.put(
            "/api/admin/projects/vis-space-hidden-child/deploy",
            files={"file": ("index.html", b"<h1>v1</h1>", "text/html")},
            data={"parent_id": str(visible_space["id"])},
            headers=bearer,
        ).json()["project"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{child_in_vis['id']}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        redeploy_vis_child = admin_client.put(
            "/api/admin/projects/vis-space-hidden-child/deploy",
            files={"file": ("index.html", b"<h1>v2</h1>", "text/html")},
            headers=bearer,
        )
        assert redeploy_vis_child.status_code == 200
        assert redeploy_vis_child.json()["project"]["visible"] is False
        assert redeploy_vis_child.json()["project"]["parent_id"] == visible_space["id"]
        assert anon_client.get("/projects/vis-space-hidden-child/index.html").status_code == 404
        assert "vis-space-hidden-child" not in anon_client.get(f"/projects/{visible_space['slug']}/").text

        child_in_hidden = admin_client.put(
            "/api/admin/projects/hidden-space-child/deploy",
            files={"file": ("index.html", b"<h1>h1</h1>", "text/html")},
            data={"parent_id": str(hidden_space["id"]), "visible": "false"},
            headers=bearer,
        ).json()["project"]
        assert child_in_hidden["visible"] is False
        redeploy_hidden_child = admin_client.put(
            "/api/admin/projects/hidden-space-child/deploy",
            files={"file": ("index.html", b"<h1>h2</h1>", "text/html")},
            headers=bearer,
        )
        assert redeploy_hidden_child.status_code == 200
        assert redeploy_hidden_child.json()["project"]["visible"] is False
        assert redeploy_hidden_child.json()["project"]["parent_id"] == hidden_space["id"]
        assert anon_client.get("/projects/hidden-space-child/index.html").status_code == 404

        assert (
            admin_client.patch(
                f"/api/admin/projects/{hidden_space['id']}",
                json={"visible": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert anon_client.get("/projects/hidden-space-child/index.html").status_code == 404


def test_locked_link_hides_target_url_and_enforces_password_gate() -> None:
    secret_url = "https://vault.example.com/private/roadmap?token=secret123"
    space_secret_url = "https://internal.example.com/space-only-doc"
    public_url = "https://public.example.com/open-docs"

    with TestClient(app) as admin_client, TestClient(app) as anon_client:
        csrf = login(admin_client)
        space = create_app(admin_client, csrf, "space", "外链测试空间").json()["project"]

        locked_link = admin_client.post(
            "/api/admin/projects/link",
            json={"url": secret_url, "title": "机密外链"},
            headers=auth_headers(csrf),
        ).json()["project"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{locked_link['id']}",
                json={"password": "LinkSecret99"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        unlocked_link = admin_client.post(
            "/api/admin/projects/link",
            json={"url": public_url, "title": "公开外链"},
            headers=auth_headers(csrf),
        ).json()["project"]

        space_locked_link = admin_client.post(
            "/api/admin/projects/link",
            json={"url": space_secret_url, "title": "空间机密外链", "parent_id": space["id"]},
            headers=auth_headers(csrf),
        ).json()["project"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{space_locked_link['id']}",
                json={"password": "SpaceLink88"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        gallery_html = anon_client.get("/").text
        assert secret_url not in gallery_html
        assert space_secret_url not in gallery_html
        assert f'href="{public_url}"' in gallery_html
        locked_card = re.search(
            rf'<a class="card"[^>]*data-slug="{re.escape(locked_link["slug"])}"[^>]*>',
            gallery_html,
            re.DOTALL,
        )
        assert locked_card is not None
        assert f'href="/projects/{locked_link["slug"]}/"' in locked_card.group(0)
        assert 'target="_blank"' not in locked_card.group(0)

        public_card = re.search(
            rf'<a class="card"[^>]*data-slug="{re.escape(unlocked_link["slug"])}"[^>]*>',
            gallery_html,
            re.DOTALL,
        )
        assert public_card is not None
        assert f'href="{public_url}"' in public_card.group(0)
        assert 'target="_blank"' in public_card.group(0)

        space_html = anon_client.get(f"/projects/{space['slug']}/").text
        assert space_secret_url not in space_html
        space_card = re.search(
            rf'<a class="card"[^>]*data-slug="{re.escape(space_locked_link["slug"])}"[^>]*>',
            space_html,
            re.DOTALL,
        )
        assert space_card is not None
        assert f'href="/projects/{space_locked_link["slug"]}/"' in space_card.group(0)
        assert 'target="_blank"' not in space_card.group(0)

        anon_search_resp = anon_client.get("/api/search")
        assert anon_search_resp.status_code == 200
        assert secret_url not in anon_search_resp.text
        assert space_secret_url not in anon_search_resp.text
        by_slug = {item["slug"]: item for item in anon_search_resp.json()}
        assert by_slug[locked_link["slug"]]["url"] == f"/projects/{locked_link['slug']}/"
        assert by_slug[locked_link["slug"]]["is_locked"] is True
        assert by_slug[space_locked_link["slug"]]["url"] == f"/projects/{space_locked_link['slug']}/"
        assert by_slug[space_locked_link["slug"]]["is_locked"] is True
        assert by_slug[unlocked_link["slug"]]["url"] == public_url
        assert by_slug[unlocked_link["slug"]]["is_locked"] is False

        admin_search = {item["slug"]: item for item in admin_client.get("/api/search").json()}
        assert admin_search[locked_link["slug"]]["url"] == secret_url

        assert (
            anon_client.get(f"/projects/{unlocked_link['slug']}/", follow_redirects=False).status_code == 404
        )

        for path in (f"/projects/{locked_link['slug']}", f"/projects/{locked_link['slug']}/"):
            gate = anon_client.get(path, follow_redirects=False)
            assert gate.status_code == 200
            assert "此作品已设置访问密码保护" in gate.text
            assert secret_url not in gate.text

        wrong = anon_client.post(
            f"/projects/{locked_link['slug']}/unlock",
            data={"password": "wrong-pass"},
            follow_redirects=False,
        )
        assert wrong.status_code == 401
        assert secret_url not in wrong.text

        unlocked = anon_client.post(
            f"/projects/{locked_link['slug']}/unlock",
            data={"password": "LinkSecret99"},
            follow_redirects=False,
        )
        assert unlocked.status_code == 303
        assert unlocked.headers["location"] == f"/projects/{locked_link['slug']}/"

        redirected = anon_client.get(f"/projects/{locked_link['slug']}/", follow_redirects=False)
        assert redirected.status_code == 302
        assert redirected.headers["location"] == secret_url
        assert redirected.headers.get("cache-control") == "no-store"

        redirected_root = anon_client.get(f"/projects/{locked_link['slug']}", follow_redirects=False)
        assert redirected_root.status_code == 302
        assert redirected_root.headers["location"] == secret_url

        assert (
            anon_client.get(f"/projects/{locked_link['slug']}/foo", follow_redirects=False).status_code == 404
        )
        assert (
            anon_client.get(f"/projects/{locked_link['slug']}/admin", follow_redirects=False).status_code
            == 404
        )

        admin_redirect = admin_client.get(f"/projects/{locked_link['slug']}/", follow_redirects=False)
        assert admin_redirect.status_code == 302
        assert admin_redirect.headers["location"] == secret_url

        assert (
            admin_client.patch(
                f"/api/admin/projects/{locked_link['id']}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert anon_client.get(f"/projects/{locked_link['slug']}/", follow_redirects=False).status_code == 404
        assert (
            anon_client.post(
                f"/projects/{locked_link['slug']}/unlock",
                data={"password": "LinkSecret99"},
                follow_redirects=False,
            ).status_code
            == 404
        )


def test_project_password_change_immediately_invalidates_old_gate_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = app.state.config
    hash_v1 = auth.hash_project_password("PassOne#1")
    hash_v2 = auth.hash_project_password("PassTwo#2")
    tok_v1 = auth.make_project_token(cfg, "unit-proj", hash_v1)
    assert auth.verify_project_token(cfg, "unit-proj", tok_v1, hash_v1) is True
    assert auth.verify_project_token(cfg, "unit-proj", tok_v1, hash_v2) is False
    assert auth.verify_project_token(cfg, "unit-proj", tok_v1, "") is False

    legacy_serializer = URLSafeTimedSerializer(cfg.secret, salt="siteflow-project-gate")
    legacy_token = legacy_serializer.dumps({"slug": "unit-proj", "ts": time.time()})
    assert auth.verify_project_token(cfg, "unit-proj", legacy_token, hash_v1) is False

    with TestClient(app) as admin_client, TestClient(app) as guest_client:
        csrf = login(admin_client)

        static_proj = admin_client.post(
            "/api/admin/projects/upload",
            files={
                "file": (
                    "locked-site.zip",
                    make_zip({"index.html": b"<h1>Secret Static</h1>", "app.css": b"body{color:red}"}),
                )
            },
            headers=auth_headers(csrf),
        ).json()["project"]
        static_id, static_slug = static_proj["id"], static_proj["slug"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{static_id}",
                json={"password": "StaticOld1"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            guest_client.post(
                f"/projects/{static_slug}/unlock",
                data={"password": "StaticOld1"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert guest_client.get(f"/projects/{static_slug}/index.html").status_code == 200
        assert "Secret Static" in guest_client.get(f"/projects/{static_slug}/index.html").text
        assert guest_client.get(f"/projects/{static_slug}/app.css").status_code == 200

        assert (
            admin_client.patch(
                f"/api/admin/projects/{static_id}",
                json={"password": "StaticNew2"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        stale_html = guest_client.get(f"/projects/{static_slug}/index.html")
        assert stale_html.status_code == 200
        assert "此作品已设置访问密码保护" in stale_html.text
        assert "Secret Static" not in stale_html.text
        assert guest_client.get(f"/projects/{static_slug}/app.css").status_code == 401

        assert (
            guest_client.post(
                f"/projects/{static_slug}/unlock",
                data={"password": "StaticNew2"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert "Secret Static" in guest_client.get(f"/projects/{static_slug}/index.html").text
        assert guest_client.get(f"/projects/{static_slug}/app.css").status_code == 200

        link_proj = admin_client.post(
            "/api/admin/projects/link",
            json={"url": "https://secret-link.example.com/doc", "title": "改密外链"},
            headers=auth_headers(csrf),
        ).json()["project"]
        link_id, link_slug = link_proj["id"], link_proj["slug"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{link_id}",
                json={"password": "LinkOld1"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            guest_client.post(
                f"/projects/{link_slug}/unlock",
                data={"password": "LinkOld1"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert guest_client.get(f"/projects/{link_slug}/", follow_redirects=False).status_code == 302
        assert (
            admin_client.patch(
                f"/api/admin/projects/{link_id}",
                json={"password": "LinkNew2"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        stale_link = guest_client.get(f"/projects/{link_slug}/", follow_redirects=False)
        assert stale_link.status_code == 200
        assert "此作品已设置访问密码保护" in stale_link.text
        assert "secret-link.example.com" not in stale_link.text

        blog = create_app(admin_client, csrf, "blog", "改密博客").json()["project"]
        blog_id, blog_slug = blog["id"], blog["slug"]
        assert (
            admin_client.post(
                f"/api/admin/projects/{blog_id}/extensions/post_cover/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        media_resp = admin_client.post(
            f"/api/admin/projects/{blog_id}/extensions/post_cover/media",
            files={"file": ("cover.png", make_png(), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        )
        assert media_resp.status_code == 200
        media_url = media_resp.json()["url"]
        assert (
            admin_client.post(
                f"/api/admin/projects/{blog_id}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "chat_access": "public",
                        "api_key": "sk-test-rotate",
                        "rate_limit_per_min": 60,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            admin_client.patch(
                f"/api/admin/projects/{blog_id}",
                json={"password": "BlogOld1"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        _patch_upstream(monkeypatch)
        assert (
            guest_client.post(
                f"/projects/{blog_slug}/unlock",
                data={"password": "BlogOld1"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert guest_client.get(media_url).status_code == 200
        assert (
            guest_client.post(
                f"/api/projects/{blog_slug}/mascot/chat",
                json={"messages": [{"role": "user", "content": "你好"}]},
                headers=ORIGIN,
            ).status_code
            == 200
        )

        assert (
            admin_client.patch(
                f"/api/admin/projects/{blog_id}",
                json={"password": "BlogNew2"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        stale_blog = guest_client.get(f"/projects/{blog_slug}/")
        assert stale_blog.status_code == 200
        assert "此作品已设置访问密码保护" in stale_blog.text
        assert guest_client.get(media_url).status_code == 401
        assert (
            guest_client.post(
                f"/api/projects/{blog_slug}/mascot/chat",
                json={"messages": [{"role": "user", "content": "旧凭证"}]},
                headers=ORIGIN,
            ).status_code
            == 401
        )
        assert (
            guest_client.post(
                f"/projects/{blog_slug}/unlock",
                data={"password": "BlogNew2"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert guest_client.get(media_url).status_code == 200
        assert (
            guest_client.post(
                f"/api/projects/{blog_slug}/mascot/chat",
                json={"messages": [{"role": "user", "content": "新凭证"}]},
                headers=ORIGIN,
            ).status_code
            == 200
        )

        bottle = create_app(admin_client, csrf, "bottle", "改密漂流瓶").json()["project"]
        bottle_id, bottle_slug = bottle["id"], bottle["slug"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{bottle_id}",
                json={"password": "BottleOld1"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            guest_client.post(
                f"/projects/{bottle_slug}/unlock",
                data={"password": "BottleOld1"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            guest_client.post(
                f"/api/projects/{bottle_slug}/bottle/throw",
                json={"message": "旧密码有效期间投瓶"},
                headers=ORIGIN,
            ).status_code
            == 200
        )

        assert (
            admin_client.patch(
                f"/api/admin/projects/{bottle_id}",
                json={"password": "BottleNew2"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        stale_bottle_page = guest_client.get(f"/projects/{bottle_slug}/")
        assert stale_bottle_page.status_code == 200
        assert "此作品已设置访问密码保护" in stale_bottle_page.text
        assert (
            guest_client.post(
                f"/api/projects/{bottle_slug}/bottle/throw",
                json={"message": "改密后旧 cookie 投瓶"},
                headers=ORIGIN,
            ).status_code
            == 401
        )
        assert (
            guest_client.post(
                f"/api/projects/{bottle_slug}/bottle/pick",
                headers=ORIGIN,
            ).status_code
            == 401
        )
        assert (
            guest_client.post(
                f"/projects/{bottle_slug}/unlock",
                data={"password": "BottleNew2"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            guest_client.post(
                f"/api/projects/{bottle_slug}/bottle/throw",
                json={"message": "新密码重新解锁投瓶"},
                headers=ORIGIN,
            ).status_code
            == 200
        )


def test_resume_long_work_summary_project_description_highlights_and_strict_limits() -> None:
    long_work_summary = "工作" * 999 + "尾端"
    long_proj_desc = "项目" * 999 + "结尾"
    long_highlight = "要" * 498 + "末尾"
    assert len(long_work_summary) == 2000
    assert len(long_proj_desc) == 2000
    assert len(long_highlight) == 500

    with TestClient(app) as client:
        csrf = login(client)
        resume = create_app(client, csrf, "resume", "长文本简历").json()["project"]
        pid, slug = resume["id"], resume["slug"]

        valid_payload: dict[str, Any] = {
            "basics": {
                "name": "陈长风",
                "label": "资深架构师",
                "summary": "简" * 1000,
                "url": "https://example.com/" + "a" * 400,
            },
            "work": [
                {
                    "name": "远航科技",
                    "position": "技术负责人",
                    "startDate": "2021-01",
                    "endDate": "至今",
                    "summary": long_work_summary,
                    "highlights": [long_highlight],
                }
            ],
            "projects": [
                {
                    "name": "分布式网关",
                    "description": long_proj_desc,
                    "highlights": [long_highlight],
                    "keywords": ["Rust", "Kubernetes"],
                }
            ],
        }
        saved = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(valid_payload, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert saved.status_code == 200, saved.text
        stored = json.loads(saved.json()["project"]["content"])
        assert stored["work"][0]["summary"] == long_work_summary
        assert stored["projects"][0]["description"] == long_proj_desc
        assert stored["work"][0]["highlights"] == [long_highlight]
        assert stored["projects"][0]["highlights"] == [long_highlight]

        page = client.get(f"/projects/{slug}/")
        assert page.status_code == 200
        assert long_work_summary in page.text
        assert long_proj_desc in page.text
        assert long_highlight in page.text

        over_work = dict(valid_payload)
        over_work["work"] = [{**valid_payload["work"][0], "summary": "超" * 2001}]
        resp_work = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(over_work, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert resp_work.status_code == 422
        assert "2000" in resp_work.json()["error"]

        over_proj = dict(valid_payload)
        over_proj["projects"] = [{**valid_payload["projects"][0], "description": "超" * 2001}]
        resp_proj = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(over_proj, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert resp_proj.status_code == 422
        assert "2000" in resp_proj.json()["error"]

        over_hl = dict(valid_payload)
        over_hl["work"] = [{**valid_payload["work"][0], "highlights": ["点" * 501]}]
        resp_hl = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(over_hl, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert resp_hl.status_code == 422
        assert "500" in resp_hl.json()["error"]

        over_short = dict(valid_payload)
        over_short["basics"] = {**valid_payload["basics"], "name": "名" * 201}
        resp_short = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(over_short, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert resp_short.status_code == 422
        assert "200" in resp_short.json()["error"]

        over_url = dict(valid_payload)
        over_url["basics"] = {**valid_payload["basics"], "url": "https://example.com/" + "u" * 490}
        resp_url = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(over_url, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert resp_url.status_code == 422
        assert "500" in resp_url.json()["error"]

        after_reject = json.loads(
            client.get(f"/api/admin/projects/{pid}", headers=auth_headers(csrf)).json()["project"]["content"]
        )
        assert after_reject["work"][0]["summary"] == long_work_summary
        assert after_reject["projects"][0]["description"] == long_proj_desc

        admin_html = client.get(f"/admin/projects/{pid}").text
        assert 'id="f-name" maxlength="200"' in admin_html
        assert 'id="f-url" maxlength="500"' in admin_html
        assert 'id="f-summary" rows="3" maxlength="2000"' in admin_html
        assert 'input.setAttribute("maxlength", String(maxLen))' in admin_html

    clamped = validate_resume(
        json.dumps(
            {
                "work": [{"summary": "x" * 2100, "highlights": ["h" * 600]}],
                "projects": [{"description": "p" * 2100}],
            }
        ),
        strict=False,
    )
    assert len(clamped["work"][0]["summary"]) == 2000
    assert len(clamped["work"][0]["highlights"][0]) == 500
    assert len(clamped["projects"][0]["description"]) == 2000


def test_resume_editing_other_fields_preserves_existing_avatar_and_allows_explicit_clear() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        resume = create_app(client, csrf, "resume", "头像保留简历").json()["project"]
        pid, slug = resume["id"], resume["slug"]

        initial = {
            "basics": {
                "name": "林深",
                "label": "架构师",
                "image": "portrait-avatar.webp",
                "summary": "初始简介",
            },
            "work": [],
        }
        first = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(initial, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert first.status_code == 200
        assert json.loads(first.json()["project"]["content"])["basics"]["image"] == "portrait-avatar.webp"
        assert "/media/covers/portrait-avatar.webp" in client.get(f"/projects/{slug}/").text

        admin_html = client.get(f"/admin/projects/{pid}").text
        assert (
            'image: (state.basics && typeof state.basics.image === "string") ? state.basics.image : ""'
            in admin_html
        )

        omitted_image_payload = {
            "basics": {
                "name": "林深（更新后）",
                "label": "首席架构师",
                "summary": "修改了其他字段但未传 image 键",
            },
            "work": [{"name": "星云科技", "position": "首席架构师"}],
        }
        second = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(omitted_image_payload, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert second.status_code == 200
        second_content = json.loads(second.json()["project"]["content"])
        assert second_content["basics"]["name"] == "林深（更新后）"
        assert second_content["basics"]["image"] == "portrait-avatar.webp"
        assert "/media/covers/portrait-avatar.webp" in client.get(f"/projects/{slug}/").text

        explicit_keep_payload = {
            "basics": {
                "name": "林深（再次更新）",
                "image": "portrait-avatar.webp",
            }
        }
        third = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(explicit_keep_payload, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert third.status_code == 200
        assert json.loads(third.json()["project"]["content"])["basics"]["image"] == "portrait-avatar.webp"

        explicit_clear_payload = {
            "basics": {
                "name": "林深（清空头像）",
                "image": "",
            }
        }
        fourth = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(explicit_clear_payload, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert fourth.status_code == 200
        assert json.loads(fourth.json()["project"]["content"])["basics"]["image"] == ""
        assert "/media/covers/portrait-avatar.webp" not in client.get(f"/projects/{slug}/").text
