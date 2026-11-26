import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from app import project_service, store
from app.auth import verify_project_password
from app.deps import ServiceError
from app.extensions.registry import referenced_media_urls
from app.main import app
from app.og import OpenGraph


def _png_bytes(color: tuple[int, int, int] = (20, 120, 220)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (48, 32), color).save(buf, format="PNG")
    return buf.getvalue()


def _media_path(url: str) -> Path:
    return Path(app.state.config.data) / url.lstrip("/")


def test_slug_validation_and_parent_resolution() -> None:
    assert project_service.validate_slug("demo-work_1") == "demo-work_1"
    for bad in ("", "UPPER", "-lead", "bad slug", "a/b", "../x", "a" * 65):
        with pytest.raises(ServiceError) as exc_info:
            project_service.validate_slug(bad)
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == "invalid_slug"

    with store.session() as db:
        with pytest.raises(ServiceError) as missing_slug:
            project_service.get_project_by_slug(db, "does-not-exist")
        assert missing_slug.value.status_code == 404
        assert missing_slug.value.code == "not_found"

        with pytest.raises(ServiceError) as missing_id:
            project_service.get_project_by_id(db, 999999)
        assert missing_id.value.status_code == 404
        assert missing_id.value.code == "not_found"

        assert project_service.resolve_parent_by_id(db, None) is None
        assert project_service.resolve_parent_by_slug(db, None) is None

        s1 = project_service.create_app_project(db, app_type="space", title="一级空间", slug="s1")
        s2 = project_service.create_app_project(
            db, app_type="space", title="二级空间", parent_id=s1.id, slug="s2"
        )
        s3 = project_service.create_app_project(
            db, app_type="space", title="三级空间", parent_id=s2.id, slug="s3"
        )
        blog = project_service.create_app_project(
            db, app_type="blog", title="叶子博客", parent_id=s1.id, slug="leaf-blog"
        )

        assert project_service.resolve_parent_by_slug(db, "s2") == s2

        with pytest.raises(ServiceError) as too_deep:
            project_service.resolve_parent_by_id(db, s3.id)
        assert too_deep.value.status_code == 400
        assert too_deep.value.code == "max_depth_exceeded"

        with pytest.raises(ServiceError) as leaf_err:
            project_service.resolve_parent_by_slug(db, blog.slug)
        assert leaf_err.value.status_code == 400
        assert leaf_err.value.code == "invalid_parent"


def test_tree_flat_views_and_allowed_slugs_inheritance() -> None:
    config = app.state.config
    with store.session() as db:
        space_a = project_service.create_app_project(db, app_type="space", title="空间 A", slug="space-a")
        space_sub = project_service.create_app_project(
            db, app_type="space", title="子空间 A1", parent_id=space_a.id, slug="space-a1"
        )
        blog_deep = project_service.create_app_project(
            db, app_type="blog", title="深层博客", parent_id=space_sub.id, slug="blog-deep"
        )
        link_a = project_service.create_link_project(
            db,
            config,
            url="https://example.com/docs",
            title="文档外链",
            parent_id=space_a.id,
            slug="link-a",
            fetch_og_fn=lambda url: None,
            fetch_image_fn=lambda url: None,
        )
        space_b = project_service.create_app_project(db, app_type="space", title="空间 B", slug="space-b")
        resume_b = project_service.create_app_project(
            db, app_type="resume", title="简历 B", parent_id=space_b.id, slug="resume-b"
        )
        pinned_blog = project_service.create_app_project(
            db, app_type="blog", title="置顶博客", slug="blog-pinned"
        )
        project_service.patch_project_meta(db, config, pinned_blog, pinned=True)

        tree = project_service.list_projects_view(db, view="tree")
        assert [node["slug"] for node in tree] == ["blog-pinned", "space-b", "space-a"]
        for node in tree:
            assert "content" not in node
            assert node["public_url"] == f"/projects/{node['slug']}/"

        node_a = next(n for n in tree if n["slug"] == "space-a")
        assert [c["slug"] for c in node_a["children"]] == ["link-a", "space-a1"]
        node_sub = next(c for c in node_a["children"] if c["slug"] == "space-a1")
        assert node_sub["parent_slug"] == "space-a"
        assert [c["slug"] for c in node_sub["children"]] == ["blog-deep"]
        assert node_sub["children"][0]["parent_slug"] == "space-a1"

        flat_under_a = project_service.list_projects_view(db, view="flat", parent_slug="space-a")
        assert [item["slug"] for item in flat_under_a] == ["link-a", "space-a1"]
        assert all(item["parent_slug"] == "space-a" for item in flat_under_a)

        flat_blogs = project_service.list_projects_view(db, view="flat", project_type="blog")
        assert {item["slug"] for item in flat_blogs} == {"blog-pinned", "blog-deep"}

        scoped_tree = project_service.list_projects_view(
            db, view="tree", allowed_slugs=frozenset({"space-a"})
        )
        assert [n["slug"] for n in scoped_tree] == ["space-a"]
        scoped_flat = project_service.list_projects_view(
            db, view="flat", allowed_slugs=frozenset({"space-a"})
        )
        assert {n["slug"] for n in scoped_flat} == {"space-a", "space-a1", "blog-deep", "link-a"}

        leaf_scoped_tree = project_service.list_projects_view(
            db, view="tree", allowed_slugs=frozenset({"blog-deep"})
        )
        assert [n["slug"] for n in leaf_scoped_tree] == ["blog-deep"]
        assert leaf_scoped_tree[0]["parent_slug"] == "space-a1"

        detail = project_service.project_detail(db, config, space_a)
        assert detail["project"]["slug"] == "space-a"
        assert "content" not in detail["project"]
        assert isinstance(detail["content"], dict)
        assert [c["slug"] for c in detail["children"]] == ["link-a", "space-a1"]
        assert "today_pv" in detail["stats"]

        with pytest.raises(ServiceError) as bad_view:
            project_service.list_projects_view(db, view="grid")
        assert bad_view.value.status_code == 400
        assert bad_view.value.code == "invalid_view"

        assert link_a.id and resume_b.id and blog_deep.id


def test_create_slug_conflicts_and_link_og_cover() -> None:
    config = app.state.config
    with store.session() as db:
        project_service.create_app_project(db, app_type="blog", title="主博客", slug="taken-slug")

        with pytest.raises(ServiceError) as app_conflict:
            project_service.create_app_project(db, app_type="space", title="冲突", slug="taken-slug")
        assert app_conflict.value.status_code == 409
        assert app_conflict.value.code == "slug_exists"

        with pytest.raises(ServiceError) as link_conflict:
            project_service.create_link_project(
                db,
                config,
                url="https://example.com",
                slug="taken-slug",
                fetch_og_fn=lambda url: None,
                fetch_image_fn=lambda url: None,
            )
        assert link_conflict.value.status_code == 409
        assert link_conflict.value.code == "slug_exists"

        link = project_service.create_link_project(
            db,
            config,
            url="https://example.com/article",
            slug="og-link",
            fetch_og_fn=lambda url: OpenGraph(
                title="OG 标题",
                description="OG 描述",
                image_url="https://example.com/cover.png",
            ),
            fetch_image_fn=lambda url: _png_bytes(),
        )
        assert link.slug == "og-link"
        assert link.title == "OG 标题"
        assert link.description == "OG 描述"
        assert link.cover == "og-link.webp"
        assert (Path(config.data) / "media" / "covers" / "og-link.webp").is_file()


def test_blog_post_partial_patch_idempotent_put_and_slug_conflict() -> None:
    config = app.state.config
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with store.session() as db:
        blog = project_service.create_app_project(db, app_type="blog", title="技术专栏", slug="tech-blog")
        cover_info = project_service.upload_blog_media(config, blog, _png_bytes((90, 50, 180)), kind="cover")
        cover_url = cover_info["url"]

        created = project_service.create_blog_post(
            db,
            config,
            blog,
            {
                "slug": "hello-world",
                "title": "初始标题",
                "tags": ["Python", "架构"],
                "summary": "原始摘要",
                "body": "完整正文内容，不能被局部 PATCH 丢失。",
                "meta": {"cover": cover_url, "cover_alt": "封面说明"},
            },
        )
        assert created["slug"] == "hello-world"
        assert created["date"] == today
        assert created["url"] == "/projects/tech-blog/posts/hello-world"
        assert "draft" not in created

        with pytest.raises(ServiceError) as dup_create:
            project_service.create_blog_post(
                db, config, blog, {"slug": "hello-world", "title": "重复文章", "body": "x"}
            )
        assert dup_create.value.status_code == 409
        assert dup_create.value.code == "post_slug_exists"

        with pytest.raises(ServiceError) as empty_title:
            project_service.create_blog_post(db, config, blog, {"title": "   ", "body": "x"})
        assert empty_title.value.status_code == 422

        patched = project_service.patch_blog_post(
            db,
            config,
            blog,
            "hello-world",
            {"title": "仅修改标题"},
        )
        assert patched["title"] == "仅修改标题"
        assert patched["date"] == today
        assert patched["tags"] == ["Python", "架构"]
        assert patched["summary"] == "原始摘要"
        assert patched["body"] == "完整正文内容，不能被局部 PATCH 丢失。"
        assert patched["meta"] == {"cover": cover_url, "cover_alt": "封面说明"}
        assert "draft" not in patched

        meta_trimmed = project_service.patch_blog_post(
            db,
            config,
            blog,
            "hello-world",
            {"meta": {"cover_alt": ""}},
        )
        assert meta_trimmed["meta"] == {"cover": cover_url}

        upserted_1, was_created_1 = project_service.upsert_blog_post(
            db,
            config,
            blog,
            "weekly-note",
            {
                "slug": "ignored-slug",
                "title": "周报第一版",
                "tags": ["周报"],
                "body": "第一版正文",
                "meta": {"cover": cover_url},
            },
        )
        assert was_created_1 is True
        assert upserted_1["slug"] == "weekly-note"
        assert upserted_1["date"] == today
        assert upserted_1["meta"] == {"cover": cover_url}

        upserted_2, was_created_2 = project_service.upsert_blog_post(
            db,
            config,
            blog,
            "weekly-note",
            {
                "title": "周报第二版",
                "tags": ["周报", "复盘"],
                "body": "第二版正文",
            },
        )
        assert was_created_2 is False
        assert upserted_2["slug"] == "weekly-note"
        assert upserted_2["title"] == "周报第二版"
        assert upserted_2["date"] == today
        assert upserted_2["meta"] == {"cover": cover_url}

        listed = project_service.list_blog_posts(config, blog)
        assert len(listed) == 2
        assert all("body" not in item for item in listed)
        assert all(item["url"].startswith("/projects/tech-blog/posts/") for item in listed)

        listed_with_body = project_service.list_blog_posts(
            config, blog, tag="python", q="完整正文", include_body=True
        )
        assert [p["slug"] for p in listed_with_body] == ["hello-world"]
        assert "完整正文" in listed_with_body[0]["body"]

        with pytest.raises(ServiceError) as rename_conflict:
            project_service.patch_blog_post(db, config, blog, "weekly-note", {}, new_slug="hello-world")
        assert rename_conflict.value.status_code == 409
        assert rename_conflict.value.code == "post_slug_exists"

        with pytest.raises(ServiceError) as bad_put_slug:
            project_service.upsert_blog_post(db, config, blog, "../escape", {"title": "坏标识"})
        assert bad_put_slug.value.status_code == 400
        assert bad_put_slug.value.code == "invalid_post_slug"

        renamed = project_service.patch_blog_post(
            db, config, blog, "weekly-note", {}, new_slug="weekly-note-v2"
        )
        assert renamed["slug"] == "weekly-note-v2"
        assert project_service.get_blog_post(config, blog, "weekly-note-v2")["title"] == "周报第二版"


def test_blog_body_image_upload_reference_protection_and_auto_cleanup() -> None:
    config = app.state.config
    with store.session() as db:
        blog = project_service.create_app_project(db, app_type="blog", title="插图博客", slug="img-blog")
        space = project_service.create_app_project(db, app_type="space", title="非博客", slug="not-blog")

        with pytest.raises(ServiceError) as non_blog_err:
            project_service.upload_blog_media(config, space, _png_bytes(), kind="image")
        assert non_blog_err.value.status_code == 400

        with pytest.raises(ServiceError) as bad_kind:
            project_service.upload_blog_media(config, blog, _png_bytes(), kind="avatar")
        assert bad_kind.value.status_code == 400
        assert bad_kind.value.code == "invalid_media_kind"

        img1 = project_service.upload_blog_media(config, blog, _png_bytes((10, 10, 200)), kind="image")
        img2 = project_service.upload_blog_media(config, blog, _png_bytes((200, 10, 10)), kind="image")
        url1, url2 = img1["url"], img2["url"]
        assert url1.startswith("/media/blog/img-blog/image-") and url1.endswith(".webp")
        assert img1["markdown"] == f"![]({url1})"
        assert _media_path(url1).is_file()
        assert _media_path(url2).is_file()

        project_service.create_blog_post(
            db,
            config,
            blog,
            {
                "slug": "post-a",
                "title": "文章 A",
                "body": f"共享图：![a]({url1})\n独享图：![b]({url2})",
            },
        )
        project_service.create_blog_post(
            db,
            config,
            blog,
            {
                "slug": "post-b",
                "title": "文章 B",
                "body": f"同样引用：![]({url1})",
            },
        )

        parsed = project_service.parsed_project_content(blog, config)
        refs = referenced_media_urls(parsed, target="blog", config=config)
        assert url1 in refs and url2 in refs

        project_service.patch_blog_post(db, config, blog, "post-a", {"title": "文章 A 改标题"})
        assert _media_path(url1).is_file()
        assert _media_path(url2).is_file()

        project_service.patch_blog_post(db, config, blog, "post-a", {"body": f"仅保留：![]({url1})"})
        assert _media_path(url1).is_file()
        assert not _media_path(url2).exists()

        project_service.delete_blog_post(db, config, blog, "post-a")
        assert _media_path(url1).is_file()

        project_service.delete_blog_post(db, config, blog, "post-b")
        assert not _media_path(url1).exists()


def test_patch_project_content_merge_and_extension_secret_preservation() -> None:
    config = app.state.config
    secret_key = "sk-live-secret-do-not-leak"
    with store.session() as db:
        resume = project_service.create_app_project(
            db, app_type="resume", title="林深简历", slug="lin-resume"
        )
        initial = {
            "basics": {
                "name": "林深",
                "label": "架构师",
                "image": "avatar.webp",
                "email": "lin@example.com",
                "location": {"city": "上海", "region": "浦东", "countryCode": "CN"},
            },
            "work": [{"name": "星云科技", "position": "首席架构师"}],
            "extensions": {
                "mascot": {
                    "mode": "override",
                    "cascade": False,
                    "config": {
                        "character": "dafeiyu",
                        "greeting": "旧欢迎语",
                        "api_key": secret_key,
                    },
                }
            },
        }
        saved_initial = project_service.patch_project_content(db, config, resume, initial, merge=False)
        assert saved_initial["extensions"]["mascot"]["config"]["api_key"] == ""
        raw_stored = json.loads(resume.content)
        assert raw_stored["extensions"]["mascot"]["config"]["api_key"] == secret_key

        partial_updated = project_service.patch_project_content(
            db,
            config,
            resume,
            {"basics": {"label": "首席系统架构师", "location": {"city": "深圳"}}},
            merge=True,
        )
        assert partial_updated["basics"]["name"] == "林深"
        assert partial_updated["basics"]["image"] == "avatar.webp"
        assert partial_updated["basics"]["email"] == "lin@example.com"
        assert partial_updated["basics"]["label"] == "首席系统架构师"
        assert partial_updated["basics"]["location"] == {
            "city": "深圳",
            "region": "浦东",
            "countryCode": "CN",
        }
        assert len(partial_updated["work"]) == 1
        assert partial_updated["extensions"]["mascot"]["config"]["api_key"] == ""
        assert json.loads(resume.content)["extensions"]["mascot"]["config"]["api_key"] == secret_key

        ext_updated = project_service.patch_project_content(
            db,
            config,
            resume,
            {
                "extensions": {
                    "mascot": {
                        "mode": "override",
                        "cascade": False,
                        "config": {"greeting": "新欢迎语", "api_key": ""},
                    }
                }
            },
            merge=True,
        )
        assert ext_updated["extensions"]["mascot"]["config"]["greeting"] == "新欢迎语"
        assert ext_updated["extensions"]["mascot"]["config"]["api_key"] == ""
        assert json.loads(resume.content)["extensions"]["mascot"]["config"]["api_key"] == secret_key

        space = project_service.create_app_project(db, app_type="space", title="主题空间", slug="theme-sp")
        sp_v1 = project_service.patch_project_content(
            db, config, space, {"accent": "#0ea5e9", "font_family": "serif"}, merge=True
        )
        assert sp_v1["accent"] == "#0ea5e9" and sp_v1["font_family"] == "serif"
        sp_v2 = project_service.patch_project_content(db, config, space, {"radius_card": "20px"}, merge=True)
        assert sp_v2["accent"] == "#0ea5e9"
        assert sp_v2["font_family"] == "serif"
        assert sp_v2["radius_card"] == "20px"

        bottle = project_service.create_app_project(db, app_type="bottle", title="海滩", slug="beach-bottle")
        bt_v1 = project_service.patch_project_content(
            db, config, bottle, {"intro": "自定义欢迎语", "max_length": 400}, merge=True
        )
        assert bt_v1["intro"] == "自定义欢迎语" and bt_v1["max_length"] == 400
        bt_v2 = project_service.patch_project_content(db, config, bottle, {"allow_links": True}, merge=True)
        assert bt_v2["intro"] == "自定义欢迎语"
        assert bt_v2["max_length"] == 400
        assert bt_v2["allow_links"] is True

        link = project_service.create_link_project(
            db,
            config,
            url="https://example.com",
            slug="plain-link",
            fetch_og_fn=lambda url: None,
            fetch_image_fn=lambda url: None,
        )
        with pytest.raises(ServiceError) as unsupported:
            project_service.patch_project_content(db, config, link, {"foo": "bar"})
        assert unsupported.value.status_code == 400
        assert unsupported.value.code == "unsupported_content_type"


def test_patch_project_meta_cycle_depth_blog_sync_password_cover_and_cascade() -> None:
    config = app.state.config
    with store.session() as db:
        root_a = project_service.create_app_project(db, app_type="space", title="根空间 A", slug="root-a")
        child_a = project_service.create_app_project(
            db, app_type="space", title="子空间 A", parent_id=root_a.id, slug="child-a"
        )
        grand_blog = project_service.create_app_project(
            db, app_type="blog", title="孙级博客", parent_id=child_a.id, slug="grand-blog"
        )
        root_b = project_service.create_app_project(db, app_type="space", title="根空间 B", slug="root-b")
        child_b = project_service.create_app_project(
            db, app_type="space", title="子空间 B", parent_id=root_b.id, slug="child-b"
        )

        with pytest.raises(ServiceError) as self_cycle:
            project_service.patch_project_meta(db, config, root_a, parent_id=root_a.id, update_parent=True)
        assert self_cycle.value.status_code == 400
        assert self_cycle.value.code == "parent_cycle"

        with pytest.raises(ServiceError) as desc_cycle:
            project_service.patch_project_meta(db, config, root_a, parent_id=child_a.id, update_parent=True)
        assert desc_cycle.value.status_code == 400
        assert desc_cycle.value.code == "parent_cycle"

        with pytest.raises(ServiceError) as depth_overflow:
            project_service.patch_project_meta(db, config, child_a, parent_id=child_b.id, update_parent=True)
        assert depth_overflow.value.status_code == 400
        assert depth_overflow.value.code == "max_depth_exceeded"

        project_service.patch_project_meta(db, config, grand_blog, title="同步博客名", description="同步简介")
        assert grand_blog.parent_id == child_a.id
        synced = project_service.parsed_project_content(grand_blog, config)
        assert synced["title"] == "同步博客名"
        assert synced["description"] == "同步简介"

        project_service.patch_project_meta(db, config, grand_blog, parent_id=None, update_parent=True)
        assert grand_blog.parent_id is None

        project_service.patch_project_meta(db, config, grand_blog, password="SecretPass!42")
        assert grand_blog.password_hash is not None
        assert verify_project_password(grand_blog.password_hash, "SecretPass!42")

        for clear_token in ("clear", "none", ""):
            project_service.patch_project_meta(db, config, grand_blog, password="TempPassword1")
            assert grand_blog.password_hash is not None
            project_service.patch_project_meta(db, config, grand_blog, password=clear_token)
            assert grand_blog.password_hash is None

        project_service.replace_cover(db, config, grand_blog, _png_bytes((50, 180, 90)))
        first_cover = grand_blog.cover
        assert (Path(config.data) / "media" / "covers" / first_cover).is_file()

        project_service.replace_cover(db, config, grand_blog, _png_bytes((180, 90, 50)))
        second_cover = grand_blog.cover
        assert second_cover != first_cover
        assert not (Path(config.data) / "media" / "covers" / first_cover).exists()
        assert (Path(config.data) / "media" / "covers" / second_cover).is_file()

        project_service.remove_cover(db, config, grand_blog)
        assert grand_blog.cover == ""
        assert not (Path(config.data) / "media" / "covers" / second_cover).exists()

        project_service.patch_project_meta(db, config, grand_blog, parent_id=child_a.id, update_parent=True)
        uploaded = project_service.upload_blog_media(config, grand_blog, _png_bytes(), kind="image")
        assert _media_path(uploaded["url"]).is_file()

        project_service.delete_project_cascade(db, config, root_a)
        assert store.by_slug(db, "root-a") is None
        assert store.by_slug(db, "child-a") is None
        assert store.by_slug(db, "grand-blog") is None
        assert not _media_path(uploaded["url"]).exists()
