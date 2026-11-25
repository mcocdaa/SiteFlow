import json
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app import store, submissions
from app.main import app
from app.plugins.bottle.plugin import BOTTLE_CSP, BottleApp, bottle_cookie_name, validate_content
from tests.test_apps import create_app
from tests.test_flow import ORIGIN, auth_headers, login


def _create_bottle(
    client: TestClient,
    csrf: str,
    title: str = "星海漂流瓶",
    parent_id: int | None = None,
) -> dict:
    resp = create_app(client, csrf, "bottle", title, parent_id=parent_id)
    assert resp.status_code == 200, resp.text
    return resp.json()["project"]


def _patch_bottle_config(client: TestClient, csrf: str, project_id: int, overrides: dict) -> dict:
    cfg = {**BottleApp().default_content(), **overrides}
    resp = client.patch(
        f"/api/admin/projects/{project_id}",
        json={"content": json.dumps(cfg, ensure_ascii=False)},
        headers=auth_headers(csrf),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["project"]


def test_submissions_module_is_generic_and_hashes_ip() -> None:
    source = Path("app/submissions.py").read_text(encoding="utf-8")
    assert "bottle" not in source.lower()

    cfg = app.state.config
    h1 = submissions.hash_ip(cfg, "203.0.113.10")
    h2 = submissions.hash_ip(cfg, "203.0.113.10")
    h3 = submissions.hash_ip(cfg, "203.0.113.11")
    assert h1 == h2
    assert h1 != h3
    assert "203.0.113.10" not in h1
    assert submissions.is_valid_ip_hash(h1)


def test_contains_link_detection_and_false_positives() -> None:
    blocked_samples = [
        "快来看 http://example.com/path",
        "访问 https://sub.domain.org?a=1",
        "打开 www.example.com 领取",
        "下载 ftp://files.example.net/a.zip",
        "联系 mailto:hello@example.com",
        "加我 foo.com",
        "电报频道 t.me/demo",
        "短链 bit.ly/3xyz",
        "官网 x.cn",
        "全角点 foo．com",
        "中文句号混淆 t。me",
        "空格混淆 foo . com",
        "短链空格混淆 t . me",
        "后缀空格 foo. com",
        "括号混淆 foo[.]com",
        "英文点混淆 foo (dot) com",
        "中文点混淆 foo 点 com",
        "全角网址 ｈｔｔｐｓ：／／ｅｘａｍｐｌｅ．ｃｏｍ",
        "零宽字符 ht\u200btps://spam.xyz",
        "直连 IP 198.51.100.42",
    ]
    for sample in blocked_samples:
        assert submissions.contains_link(sample) is True, sample

    allowed_samples = [
        "今天海风很轻，愿拾起这个瓶子的你一切顺利。",
        "Good morning. In the end, everything will be okay.",
        "I enjoy writing Python. It is fun to build things.",
        "圆周率约为 3.14，当前版本是 v2.3。",
        "1. 好好吃饭\n2. 早点休息",
        "愿你前路坦荡，所遇皆温柔！",
    ]
    for sample in allowed_samples:
        assert submissions.contains_link(sample) is False, sample


def test_bottle_config_validation_and_leaf_rules() -> None:
    valid = validate_content(json.dumps({"max_length": 500, "throw_limit_per_hour": 5}))
    assert valid["max_length"] == 500
    assert valid["require_approval"] is True

    with TestClient(app) as client:
        csrf = login(client)
        bottle = _create_bottle(client, csrf, "配置测试瓶")

        for bad_payload in (
            "not-json",
            "[]",
            json.dumps({"max_length": 10}),
            json.dumps({"max_length": 1001}),
            json.dumps({"max_length": True}),
            json.dumps({"throw_limit_per_hour": 0}),
            json.dumps({"throw_limit_per_hour": 21}),
            json.dumps({"pick_limit_per_hour": 0}),
            json.dumps({"pick_limit_per_hour": 101}),
            json.dumps({"require_approval": "yes"}),
        ):
            resp = client.patch(
                f"/api/admin/projects/{bottle['id']}",
                json={"content": bad_payload},
                headers=auth_headers(csrf),
            )
            assert resp.status_code == 422, bad_payload

        nested = create_app(client, csrf, "space", "禁止嵌套子项", parent_id=bottle["id"])
        assert nested.status_code == 400
        assert "可包含子项" in nested.json()["error"]


def test_approval_workflow_and_throw_to_pick_and_no_self_pick() -> None:
    with TestClient(app) as admin_client:
        csrf = login(admin_client)
        bottle = _create_bottle(admin_client, csrf, "心愿漂流瓶")
        slug = bottle["slug"]
        pid = bottle["id"]

        page = admin_client.get(f"/projects/{slug}/")
        assert page.status_code == 200
        assert page.headers.get("content-security-policy") == BOTTLE_CSP
        assert f'href="/admin/projects/{pid}"' in page.text

        redirect_admin = admin_client.get(f"/p/{slug}/admin", follow_redirects=False)
        assert redirect_admin.status_code == 302
        assert redirect_admin.headers["location"] == f"/admin/projects/{pid}"

        with TestClient(app) as visitor_a, TestClient(app) as visitor_b:
            headers_a = {**ORIGIN, "X-Forwarded-For": "198.51.100.1"}
            headers_b = {**ORIGIN, "X-Forwarded-For": "198.51.100.2"}

            pick_without_throw = visitor_b.post(f"/api/projects/{slug}/bottle/pick", headers=headers_b)
            assert pick_without_throw.status_code == 400
            assert "先投出一个漂流瓶" in pick_without_throw.json()["error"]

            throw_a = visitor_a.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "愿你在远方安好", "nickname": "阿海"},
                headers=headers_a,
            )
            assert throw_a.status_code == 200, throw_a.text
            data_a = throw_a.json()
            assert data_a["ok"] is True
            assert data_a["status"] == "pending"
            assert "等待站长审核" in data_a["message"]
            assert data_a["credits"] == 1
            sub_a_id = data_a["submission_id"]

            throw_b = visitor_b.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "今天的晚霞很漂亮", "nickname": "小舟"},
                headers=headers_b,
            )
            assert throw_b.status_code == 200
            assert throw_b.json()["credits"] == 1

            pick_before_approve = visitor_b.post(f"/api/projects/{slug}/bottle/pick", headers=headers_b)
            assert pick_before_approve.status_code == 200
            assert pick_before_approve.json()["empty"] is True
            assert pick_before_approve.json()["bottle"] is None
            assert pick_before_approve.json()["credits"] == 1

            queue = admin_client.get(
                f"/api/admin/projects/{pid}/submissions?status=pending",
                headers=auth_headers(csrf),
            )
            assert queue.status_code == 200
            assert queue.json()["counts"]["pending"] == 2
            assert len(queue.json()["submissions"]) == 2

            approved = admin_client.post(
                f"/api/admin/projects/{pid}/submissions/{sub_a_id}/status",
                json={"action": "approve"},
                headers=auth_headers(csrf),
            )
            assert approved.status_code == 200
            assert approved.json()["submission"]["status"] == "approved"

            self_pick = visitor_a.post(f"/api/projects/{slug}/bottle/pick", headers=headers_a)
            assert self_pick.status_code == 200
            assert self_pick.json()["empty"] is True
            assert self_pick.json()["credits"] == 1

            pick_b = visitor_b.post(f"/api/projects/{slug}/bottle/pick", headers=headers_b)
            assert pick_b.status_code == 200
            picked_data = pick_b.json()
            assert picked_data["empty"] is False
            assert picked_data["bottle"]["message"] == "愿你在远方安好"
            assert picked_data["bottle"]["nickname"] == "阿海"
            assert picked_data["credits"] == 0
            assert "ip_hash" not in picked_data["bottle"]
            assert "author_token" not in picked_data["bottle"]

            pick_b_again = visitor_b.post(f"/api/projects/{slug}/bottle/pick", headers=headers_b)
            assert pick_b_again.status_code == 400
            assert "先投出一个漂流瓶" in pick_b_again.json()["error"]


def test_credits_cap_and_tampered_cookie_and_honeypot() -> None:
    with TestClient(app) as admin_client:
        csrf = login(admin_client)
        bottle = _create_bottle(admin_client, csrf, "积分与蜜罐")
        slug = bottle["slug"]
        pid = bottle["id"]
        _patch_bottle_config(
            admin_client,
            csrf,
            pid,
            {"throw_limit_per_hour": 10, "require_approval": False},
        )

        with TestClient(app) as visitor:
            headers = {**ORIGIN, "X-Forwarded-For": "198.51.100.9"}
            hp = visitor.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "机器人推广内容", "website": "https://bot.example"},
                headers=headers,
            )
            assert hp.status_code == 200
            assert hp.json()["ok"] is True
            assert hp.json()["credits"] == 0

            listed = admin_client.get(
                f"/api/admin/projects/{pid}/submissions",
                headers=auth_headers(csrf),
            )
            assert listed.json()["counts"]["total"] == 0

            last_credits = 0
            for idx in range(6):
                resp = visitor.post(
                    f"/api/projects/{slug}/bottle/throw",
                    json={"message": f"第 {idx + 1} 只瓶子"},
                    headers=headers,
                )
                assert resp.status_code == 200
                last_credits = resp.json()["credits"]
            assert last_credits == 5

            visitor.cookies.set(bottle_cookie_name(slug), "tampered-invalid-token")
            tampered_pick = visitor.post(f"/api/projects/{slug}/bottle/pick", headers=headers)
            assert tampered_pick.status_code == 400
            assert "先投出一个漂流瓶" in tampered_pick.json()["error"]


def test_link_rejection_and_length_limit_and_allow_links_toggle() -> None:
    with TestClient(app) as admin_client:
        csrf = login(admin_client)
        bottle = _create_bottle(admin_client, csrf, "禁链测试")
        slug = bottle["slug"]
        pid = bottle["id"]
        _patch_bottle_config(admin_client, csrf, pid, {"max_length": 60, "allow_links": False})

        with TestClient(app) as visitor:
            headers = {**ORIGIN, "X-Forwarded-For": "198.51.100.20"}
            too_long = visitor.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "字" * 61},
                headers=headers,
            )
            assert too_long.status_code == 400
            assert "60" in too_long.json()["error"]

            for bad_msg in (
                "来访 https://spam.example",
                "加频道 t.me/abc",
                "点开 bit.ly/123",
                "官网 x.cn",
                "加 foo．com",
                "空格 foo . com",
            ):
                blocked = visitor.post(
                    f"/api/projects/{slug}/bottle/throw",
                    json={"message": bad_msg},
                    headers=headers,
                )
                assert blocked.status_code == 400, bad_msg
                assert "链接" in blocked.json()["error"]

            bad_nick = visitor.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "正常正文内容", "nickname": "foo.com"},
                headers=headers,
            )
            assert bad_nick.status_code == 400

            _patch_bottle_config(admin_client, csrf, pid, {"max_length": 280, "allow_links": True})
            allowed = visitor.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "欢迎来看看 https://example.com"},
                headers=headers,
            )
            assert allowed.status_code == 200


def test_rate_limits_and_ip_ban_unban_and_clear() -> None:
    with TestClient(app) as admin_client:
        csrf = login(admin_client)
        bottle = _create_bottle(admin_client, csrf, "限频与封禁")
        slug = bottle["slug"]
        pid = bottle["id"]
        _patch_bottle_config(
            admin_client,
            csrf,
            pid,
            {
                "require_approval": False,
                "throw_to_pick": False,
                "throw_limit_per_hour": 2,
                "pick_limit_per_hour": 2,
            },
        )

        with TestClient(app) as visitor_a, TestClient(app) as visitor_b:
            headers_a = {**ORIGIN, "X-Forwarded-For": "198.51.100.31"}
            headers_b = {**ORIGIN, "X-Forwarded-For": "198.51.100.32"}

            r1 = visitor_a.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "第一只瓶子"},
                headers=headers_a,
            )
            r2 = visitor_a.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "第二只瓶子"},
                headers=headers_a,
            )
            r3 = visitor_a.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "第三只超限"},
                headers=headers_a,
            )
            assert r1.status_code == 200 and r2.status_code == 200
            assert r3.status_code == 429
            assert int(r3.headers["retry-after"]) >= 1

            p1 = visitor_b.post(f"/api/projects/{slug}/bottle/pick", headers=headers_b)
            p2 = visitor_b.post(f"/api/projects/{slug}/bottle/pick", headers=headers_b)
            p3 = visitor_b.post(f"/api/projects/{slug}/bottle/pick", headers=headers_b)
            assert p1.status_code == 200 and p2.status_code == 200
            assert p3.status_code == 429
            assert int(p3.headers["retry-after"]) >= 1

            submissions.reset_submission_rate_limits()
            listed = admin_client.get(
                f"/api/admin/projects/{pid}/submissions",
                headers=auth_headers(csrf),
            ).json()
            ip_hash_a = listed["submissions"][0]["ip_hash"]

            ban_resp = admin_client.post(
                f"/api/admin/projects/{pid}/submissions/ban",
                json={"ip_hash": ip_hash_a},
                headers=auth_headers(csrf),
            )
            assert ban_resp.status_code == 200
            assert any(item["ip_hash"] == ip_hash_a for item in ban_resp.json()["banned_ips"])

            assert (
                visitor_a.post(
                    f"/api/projects/{slug}/bottle/throw",
                    json={"message": "封禁后投递"},
                    headers=headers_a,
                ).status_code
                == 403
            )
            assert visitor_a.post(f"/api/projects/{slug}/bottle/pick", headers=headers_a).status_code == 403
            assert visitor_b.post(f"/api/projects/{slug}/bottle/pick", headers=headers_b).status_code == 200

            unban_resp = admin_client.delete(
                f"/api/admin/projects/{pid}/submissions/ban/{ip_hash_a}",
                headers=auth_headers(csrf),
            )
            assert unban_resp.status_code == 200
            assert unban_resp.json()["unbanned"] is True
            assert (
                visitor_a.post(
                    f"/api/projects/{slug}/bottle/throw",
                    json={"message": "解封后投递"},
                    headers=headers_a,
                ).status_code
                == 200
            )

            sub_id_1 = listed["submissions"][0]["id"]
            admin_client.post(
                f"/api/admin/projects/{pid}/submissions/{sub_id_1}/status",
                json={"action": "reject"},
                headers=auth_headers(csrf),
            )
            clear_rejected = admin_client.post(
                f"/api/admin/projects/{pid}/submissions/clear",
                json={"status": "rejected"},
                headers=auth_headers(csrf),
            )
            assert clear_rejected.status_code == 200
            assert clear_rejected.json()["deleted"] == 1
            assert clear_rejected.json()["counts"]["approved"] == 2

            clear_all = admin_client.post(
                f"/api/admin/projects/{pid}/submissions/clear",
                json={},
                headers=auth_headers(csrf),
            )
            assert clear_all.status_code == 200
            assert clear_all.json()["deleted"] == 2
            assert clear_all.json()["counts"]["total"] == 0


def test_security_origin_csrf_auth_password_xss_and_delete_cleanup() -> None:
    with TestClient(app) as admin_client:
        csrf = login(admin_client)
        space = create_app(admin_client, csrf, "space", "容器空间").json()["project"]
        bottle = _create_bottle(admin_client, csrf, "<script>alert(1)</script>瓶子", parent_id=space["id"])
        slug = bottle["slug"]
        pid = bottle["id"]
        _patch_bottle_config(
            admin_client,
            csrf,
            pid,
            {
                "intro": "<img src=x onerror=alert(2)>欢迎",
                "placeholder": '"><script>alert(3)</script>',
                "require_approval": False,
                "throw_to_pick": False,
            },
        )

        page = admin_client.get(f"/projects/{slug}/")
        assert page.status_code == 200
        assert "<script>alert(1)</script>" not in page.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
        assert "<img src=x onerror=alert(2)>" not in page.text
        assert "&lt;img src=x onerror=alert(2)&gt;" in page.text
        assert '"><script>alert(3)</script>' not in page.text

        bottle_js = Path("app/static/js/bottle.js").read_text(encoding="utf-8")
        bottle_admin_js = Path("app/static/js/bottle_admin.js").read_text(encoding="utf-8")
        assert "innerHTML" not in bottle_js
        assert "innerHTML" not in bottle_admin_js

        with TestClient(app) as anon:
            assert (
                anon.post(
                    f"/api/projects/{slug}/bottle/throw",
                    json={"message": "跨站"},
                    headers={"Origin": "https://evil.example"},
                ).status_code
                == 403
            )
            assert (
                anon.post(
                    f"/api/projects/{slug}/bottle/throw",
                    json={"message": "缺少 Origin"},
                ).status_code
                == 403
            )
            assert (
                anon.post(
                    f"/api/projects/{slug}/bottle/pick",
                    headers={"Origin": "https://evil.example"},
                ).status_code
                == 403
            )

            assert anon.get(f"/api/admin/projects/{pid}/submissions").status_code == 401
            assert (
                anon.post(
                    f"/api/admin/projects/{pid}/submissions/clear",
                    json={},
                    headers=ORIGIN,
                ).status_code
                == 401
            )
            assert (
                anon.post(
                    f"/api/admin/projects/{pid}/submissions/ban",
                    json={"ip_hash": "a" * 24},
                    headers=ORIGIN,
                ).status_code
                == 401
            )

        assert admin_client.get(f"/api/admin/projects/{pid}/submissions").status_code == 403
        assert (
            admin_client.post(
                f"/api/admin/projects/{pid}/submissions/clear",
                json={},
                headers=ORIGIN,
            ).status_code
            == 403
        )
        assert (
            admin_client.post(
                f"/api/admin/projects/{pid}/submissions/clear",
                json={},
                headers={**auth_headers(csrf), "Origin": "https://evil.example"},
            ).status_code
            == 403
        )

        bearer = {"Authorization": f"Bearer {app.state.config.api_token}"}
        assert admin_client.get(f"/api/admin/projects/{pid}/submissions", headers=bearer).status_code == 200

        admin_client.patch(
            f"/api/admin/projects/{pid}",
            json={"password": "SeaPassword99"},
            headers=auth_headers(csrf),
        )
        with TestClient(app) as locked_visitor:
            assert "此作品已设置访问密码保护" in locked_visitor.get(f"/projects/{slug}/").text
            assert (
                locked_visitor.post(
                    f"/api/projects/{slug}/bottle/throw",
                    json={"message": "未解锁投递"},
                    headers=ORIGIN,
                ).status_code
                == 401
            )
            unlocked = locked_visitor.post(
                f"/projects/{slug}/unlock",
                data={"password": "SeaPassword99"},
                follow_redirects=False,
            )
            assert unlocked.status_code == 303
            xss_throw = locked_visitor.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "<script>alert('xss')</script>", "nickname": "<b>nick</b>"},
                headers={**ORIGIN, "X-Forwarded-For": "198.51.100.55"},
            )
            assert xss_throw.status_code == 200

        admin_page = admin_client.get(f"/admin/projects/{pid}")
        assert admin_page.status_code == 200
        assert "<script>alert('xss')</script>" not in admin_page.text

        with TestClient(app) as picker:
            assert (
                picker.post(
                    f"/api/projects/{slug}/bottle/pick",
                    headers={**ORIGIN, "X-Forwarded-For": "198.51.100.56"},
                ).status_code
                == 401
            )
            assert (
                picker.post(
                    f"/projects/{slug}/unlock",
                    data={"password": "SeaPassword99"},
                    follow_redirects=False,
                ).status_code
                == 303
            )
            picked = picker.post(
                f"/api/projects/{slug}/bottle/pick",
                headers={**ORIGIN, "X-Forwarded-For": "198.51.100.56"},
            )
            assert picked.status_code == 200
            assert picked.json()["bottle"]["message"] == "<script>alert('xss')</script>"

        admin_client.patch(
            f"/api/admin/projects/{pid}",
            json={"visible": False},
            headers=auth_headers(csrf),
        )
        with TestClient(app) as hidden_visitor:
            assert hidden_visitor.get(f"/projects/{slug}/").status_code == 404
            assert (
                hidden_visitor.post(
                    f"/api/projects/{slug}/bottle/throw",
                    json={"message": "隐藏不可投"},
                    headers=ORIGIN,
                ).status_code
                == 404
            )
            assert (
                hidden_visitor.post(
                    f"/api/projects/{slug}/bottle/pick",
                    headers=ORIGIN,
                ).status_code
                == 404
            )

        ip_hash = submissions.hash_ip(app.state.config, "198.51.100.55")
        admin_client.post(
            f"/api/admin/projects/{pid}/submissions/ban",
            json={"ip_hash": ip_hash},
            headers=auth_headers(csrf),
        )

        deleted = admin_client.delete(
            f"/api/admin/projects/{space['id']}",
            headers=auth_headers(csrf),
        )
        assert deleted.status_code == 200
        with store.session() as db:
            assert submissions.list_submissions(db, project_id=pid) == []
            assert submissions.list_banned_ips(db, project_id=pid) == []


def test_delete_single_submission_and_bottle_surface() -> None:
    from types import SimpleNamespace

    with TestClient(app) as client:
        csrf = login(client)
        bottle = _create_bottle(client, csrf, "单条删除与Surface")
        pid = bottle["id"]
        slug = bottle["slug"]

        thrown = client.post(
            f"/api/projects/{slug}/bottle/throw",
            json={"message": "测试删除单条"},
            headers=ORIGIN,
        )
        assert thrown.status_code == 200
        sub_id = thrown.json()["submission_id"]

        deleted = client.post(
            f"/api/admin/projects/{pid}/submissions/{sub_id}/status",
            json={"action": "delete"},
            headers=auth_headers(csrf),
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert deleted.json()["counts"]["total"] == 0

        missing = client.post(
            f"/api/admin/projects/{pid}/submissions/{sub_id}/status",
            json={"action": "approve"},
            headers=auth_headers(csrf),
        )
        assert missing.status_code == 404

        req: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=app.state.config)))
        with store.session() as db:
            proj = store.by_id(db, pid)
            assert proj is not None
            surface = BottleApp().surface(req, proj, db)
            assert surface.capabilities == {"accepts_visitor_input", "has_items"}
            assert surface.meta.type == "bottle"
            assert surface.context("visitor")["rules"]["max_length"] == 280


def test_bottle_surface_privacy_and_inherited_extensions() -> None:
    import io
    import zipfile
    from types import SimpleNamespace

    with TestClient(app) as admin_client:
        csrf = login(admin_client)
        space = create_app(admin_client, csrf, "space", "漂流瓶父空间").json()["project"]
        bottle = _create_bottle(admin_client, csrf, "隐私与继承漂流瓶", parent_id=space["id"])
        pid = bottle["id"]
        slug = bottle["slug"]

        with TestClient(app) as visitor_a, TestClient(app) as visitor_b:
            t_pending = visitor_a.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "待审机密内容-NEVER-LEAK-PENDING", "nickname": "保密人"},
                headers={**ORIGIN, "X-Forwarded-For": "203.0.113.71"},
            )
            assert t_pending.status_code == 200
            t_ok = visitor_b.post(
                f"/api/projects/{slug}/bottle/throw",
                json={"message": "通过后的漂流瓶文本", "nickname": "旅人B"},
                headers={**ORIGIN, "X-Forwarded-For": "203.0.113.72"},
            )
            assert t_ok.status_code == 200
            approved_id = t_ok.json()["submission_id"]

        assert (
            admin_client.post(
                f"/api/admin/projects/{pid}/submissions/{approved_id}/status",
                json={"action": "approve"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        req: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=app.state.config)))
        with store.session() as db:
            proj = store.by_id(db, pid)
            assert proj is not None
            all_subs = submissions.list_submissions(db, project_id=pid)
            assert len(all_subs) == 2
            surface = BottleApp().surface(req, proj, db)
            assert surface.capabilities == {"accepts_visitor_input", "has_items"}
            visitor_ctx = surface.context("visitor")
            ai_ctx = surface.context("ai")
            assert visitor_ctx["title"] == "隐私与继承漂流瓶"
            assert visitor_ctx["approved_count"] == 1
            assert ai_ctx["approved_count"] == 1
            assert ai_ctx["rules"]["require_approval"] is True

            ai_dump = json.dumps(ai_ctx, ensure_ascii=False)
            visitor_dump = json.dumps(visitor_ctx, ensure_ascii=False)
            for dump in (ai_dump, visitor_dump):
                assert "待审机密内容-NEVER-LEAK-PENDING" not in dump
                assert "保密人" not in dump
                assert "通过后的漂流瓶文本" not in dump
                for sub in all_subs:
                    assert sub["ip_hash"] not in dump
                    assert sub["author_token"] not in dump

        pack_buf = io.BytesIO()
        with zipfile.ZipFile(pack_buf, "w") as zf:
            zf.writestr(
                "siteflow-pack.json",
                json.dumps(
                    {
                        "schema_version": 1,
                        "id": "ocean-pack",
                        "name": "海洋主题包",
                        "version": "1.0.0",
                        "plugins": ["plugins/ocean_theme"],
                    }
                ),
            )
            zf.writestr(
                "plugins/ocean_theme/plugin.json",
                json.dumps(
                    {
                        "schema_version": 1,
                        "id": "ocean_theme",
                        "name": "海洋主题",
                        "description": "测试通用主题包",
                        "version": "1.0.0",
                        "targets": ["space", "blog", "resume"],
                        "pages": ["space", "list", "post", "resume"],
                        "slot": "title_deco",
                        "mount": {"tag": "span", "class": "ocean-deco-badge"},
                        "tokens": {"--accent": "#3b82f6", "--bg": "#f2f8ff"},
                        "icon_overrides": {"globe": "assets/globe.svg"},
                        "assets": {"css": ["assets/style.css"], "js": ["assets/main.js"]},
                    }
                ),
            )
            zf.writestr("plugins/ocean_theme/assets/style.css", ".ocean-deco-badge{display:inline-flex;}")
            zf.writestr("plugins/ocean_theme/assets/main.js", "window.__oceanThemeLoaded=true;")
            zf.writestr(
                "plugins/ocean_theme/assets/globe.svg",
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/></svg>',
            )

        up = admin_client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("ocean-pack.zip", pack_buf.getvalue(), "application/zip")},
            headers=auth_headers(csrf),
        )
        assert up.status_code == 200, up.text

        assert (
            admin_client.put(
                "/api/admin/site/extensions/mascot",
                json={"mode": "override", "cascade": True, "config": {"character": "dafeiyu"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            admin_client.put(
                "/api/admin/site/extensions/ocean-pack.ocean_theme",
                json={"mode": "override", "cascade": True, "config": {}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            admin_client.put(
                "/api/admin/site/extensions/space_layout",
                json={"mode": "override", "cascade": True, "config": {"mode": "polaroid"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        page = admin_client.get(f"/projects/{slug}/")
        assert page.status_code == 200
        assert "has-mascot" in page.text
        assert "dafeiyu" in page.text
        assert "data-ext-tokens" in page.text
        assert "--accent: #3b82f6;" in page.text
        assert "--bg: #f2f8ff;" in page.text
        assert "ocean-deco-badge" in page.text
        assert "sf-icon-override" in page.text
        assert "ext_space_layout.js" not in page.text

        admin_page = admin_client.get(f"/admin/projects/{pid}")
        assert admin_page.status_code == 200
        assert 'id="bottle-extensions"' in admin_page.text
        assert "/static/js/extensions_admin.js" in admin_page.text

        override_resp = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/mascot/install",
            json={"mode": "override", "config": {"character": "whale"}},
            headers=auth_headers(csrf),
        )
        assert override_resp.status_code == 200, override_resp.text

        _patch_bottle_config(admin_client, csrf, pid, {"max_length": 300})
        after_patch = admin_client.get(f"/projects/{slug}/")
        assert after_patch.status_code == 200
        assert '"character": "whale"' in after_patch.text


def test_i18n_zh_en_keys_strictly_aligned() -> None:
    source = Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    zh_match = re.search(
        r"zh:\s*\{(.*?)\n    \},\s*\n\s*en:\s*\{(.*?)\n    \}\s*\n\s*\};",
        source,
        re.DOTALL,
    )
    assert zh_match is not None
    zh_keys = re.findall(r'"([^"]+)"\s*:', zh_match.group(1))
    en_keys = re.findall(r'"([^"]+)"\s*:', zh_match.group(2))
    assert len(zh_keys) == len(set(zh_keys))
    assert len(en_keys) == len(set(en_keys))
    assert set(zh_keys) == set(en_keys)
    assert "admin.new_bottle" in zh_keys
    assert "bottle.throw_btn" in zh_keys
