import importlib
import json

from fastapi.testclient import TestClient

from app import stats, store
from app.main import app
from tests.test_apps import create_app
from tests.test_flow import auth_headers, login, make_png, make_zip, upload


def test_replace_and_restore_cover_without_stale_url() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        project = upload(client, csrf, "封面.html", "<h1>封面</h1>".encode()).json()["project"]
        endpoint = f"/api/admin/projects/{project['id']}/cover"
        first = client.post(endpoint, files={"file": ("one.png", make_png())}, headers=auth_headers(csrf))
        first_name = first.json()["project"]["cover"]
        old_image = client.get(f"/media/covers/{first_name}")
        assert old_image.status_code == 200
        second = client.post(endpoint, files={"file": ("two.png", make_png())}, headers=auth_headers(csrf))
        second_name = second.json()["project"]["cover"]
        assert first_name != second_name, "更换封面必须使用新地址，避免旧缓存"
        assert client.get(f"/media/covers/{second_name}").status_code == 200
        assert client.get(f"/media/covers/{first_name}").status_code == 404
        invalid = client.post(endpoint, files={"file": ("bad.png", b"broken")}, headers=auth_headers(csrf))
        assert invalid.status_code == 422
        assert client.get(f"/media/covers/{second_name}").status_code == 200
        assert client.delete(endpoint).status_code == 403
        restored = client.delete(endpoint, headers=auth_headers(csrf))
        assert restored.json()["project"]["cover"] == ""
        assert client.get(f"/media/covers/{second_name}").status_code == 404


def test_blog_article_save_validation_and_independent_editing() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        project = create_app(client, csrf, "blog", "写作测试").json()["project"]
        endpoint = f"/api/admin/projects/{project['id']}/posts"
        first = client.post(
            endpoint, json={"title": "第一篇", "body": "**正文**"}, headers=auth_headers(csrf)
        )
        assert first.status_code == 200
        slug = first.json()["post"]["slug"]
        assert slug == "第一篇", "留空标识时按标题生成，不能悄悄丢掉文章"
        second = client.post(endpoint, json={"title": "第二篇", "body": "保留"}, headers=auth_headers(csrf))
        assert second.status_code == 200
        assert client.post(endpoint, json={"title": "第一篇"}, headers=auth_headers(csrf)).status_code == 422
        assert client.post(endpoint, json={"body": "无标题"}, headers=auth_headers(csrf)).status_code == 422
        assert client.post(endpoint, json={"title": "越权"}).status_code == 403
        foreign = {**auth_headers(csrf), "Origin": "https://elsewhere.test"}
        assert client.post(endpoint, json={"title": "跨站"}, headers=foreign).status_code == 403
        edited = client.patch(
            f"{endpoint}/{slug}",
            json={"title": "修改后的标题", "slug": slug, "body": "修改后的正文"},
            headers=auth_headers(csrf),
        )
        assert edited.status_code == 200
        detail = client.get(f"/api/admin/projects/{project['id']}", headers=auth_headers(csrf)).json()
        posts = json.loads(detail["project"]["content"])["posts"]
        assert len(posts) == 2
        assert any(post["title"] == "第二篇" and post["body"] == "保留" for post in posts)
        settings = client.patch(
            f"/api/admin/projects/{project['id']}",
            json={"title": "新博客标题", "description": "新描述"},
            headers=auth_headers(csrf),
        )
        saved_content = json.loads(settings.json()["project"]["content"])
        assert saved_content["title"] == "新博客标题" and saved_content["posts"] == posts
        assert "新博客标题" in client.get(f"/projects/{project['slug']}/").text
        page = client.get(f"/admin/projects/{project['id']}/posts/{slug}/edit")
        assert "修改后的正文" in page.text and 'id="post-form"' in page.text
        assert client.get(f"/admin/projects/{project['id']}/posts/不存在/edit").status_code == 404
        assert client.delete(f"{endpoint}/{slug}", headers=auth_headers(csrf)).status_code == 200
        assert (
            client.patch(
                f"{endpoint}/{slug}", json={"title": "过期编辑"}, headers=auth_headers(csrf)
            ).status_code
            == 404
        )
        client.cookies.clear()
        assert client.get(page.request.url, follow_redirects=False).status_code == 303


def test_bulk_blog_rejects_duplicates_without_losing_saved_posts() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        project = create_app(client, csrf, "blog", "验证文章").json()["project"]
        endpoint = f"/api/admin/projects/{project['id']}"
        content = {"posts": [{"slug": "same", "title": "已有文章"}]}
        assert (
            client.patch(
                endpoint, json={"content": json.dumps(content)}, headers=auth_headers(csrf)
            ).status_code
            == 200
        )
        content["posts"].append({"slug": "same", "title": "重复文章"})
        response = client.patch(endpoint, json={"content": json.dumps(content)}, headers=auth_headers(csrf))
        assert response.status_code == 422
        assert "重复" in response.json()["error"]
        saved = json.loads(client.get(endpoint, headers=auth_headers(csrf)).json()["project"]["content"])
        assert saved["posts"] == [
            {"slug": "same", "title": "已有文章", "date": "", "tags": [], "summary": "", "body": ""}
        ]


def test_stats_count_destinations_once_and_persist_unique_visitors() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        project = upload(
            client, csrf, "访问.zip", make_zip({"index.html": b"<h1>1</h1>", "style.css": b"body{}"})
        ).json()["project"]
        blog = create_app(client, csrf, "blog", "访问博客").json()["project"]
        post = client.post(
            f"/api/admin/projects/{blog['id']}/posts", json={"title": "统计文章"}, headers=auth_headers(csrf)
        ).json()["post"]
        client.get("/")
        client.get(f"/projects/{project['slug']}/")
        with store.session() as db:
            assert stats.get_7day_stats(db)["today_pv"] == 0, "管理员预览不计入访客流量"
        client.cookies.clear()
        client.get("/")
        client.get(f"/projects/{project['slug']}/")
        client.get(f"/projects/{project['slug']}/style.css")
        client.get(f"/projects/{project['slug']}/missing.html")
        client.get(f"/projects/{project['slug']}/", headers={"sec-fetch-dest": "iframe"})
        client.get(f"/projects/{blog['slug']}/posts/{post['slug']}")
        with store.session() as db:
            site = stats.get_7day_stats(db)
            assert site["today_pv"] == 3, "首页、作品和文章各计一次，跳转和资源不计入"
            assert site["today_uv"] == 1, "同一访客跨项目访问只计一个站点 UV"
            assert stats.get_7day_stats(db, project["id"])["today_pv"] == 1
            assert stats.get_7day_stats(db, blog["id"])["today_pv"] == 1
        importlib.reload(stats)
        store._factory = None
        client.get(f"/projects/{project['slug']}/")
        with store.session() as db:
            assert stats.get_7day_stats(db)["today_uv"] == 1, "重启后当天访客仍去重"
            assert stats.get_7day_stats(db)["today_pv"] == 4
