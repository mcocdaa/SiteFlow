import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.main import STATIC_DIR, app, create_app
from app.plugins.blog.markdown import (
    BLOG_CSP,
    RenderedMarkdown,
    TocItem,
    render_inline_math,
    render_markdown,
)
from app.views import SANDBOX_CSP
from tests.test_apps import create_app as create_project_app
from tests.test_flow import auth_headers, login


def test_gfm_tables_strikethrough_tasklists_and_footnotes() -> None:
    body = (
        "| 列一 | 列二 |\n"
        "| --- | --- |\n"
        "| A | B |\n\n"
        "~~已废弃~~\n\n"
        "- [x] 已完成\n"
        "- [ ] 待办\n\n"
        "正文引用[^1]\n\n"
        "[^1]: https://root.cern/\n"
    )
    res = render_markdown(body)
    assert isinstance(res, RenderedMarkdown)
    assert '<div class="table-wrap"><table>' in res.html
    assert "</table>\n</div>" in res.html
    assert "<s>已废弃</s>" in res.html
    assert 'class="contains-task-list"' in res.html
    assert 'type="checkbox"' in res.html
    assert 'disabled="disabled"' in res.html
    assert 'checked="checked"' in res.html
    assert 'class="footnote-ref"' in res.html
    assert 'class="footnotes"' in res.html
    assert 'href="https://root.cern/"' in res.html
    assert res.has_math is False


def test_links_autolink_external_attrs_and_no_fuzzy_filenames() -> None:
    body = (
        ">https://root.cern/manual/tmva/\n\n"
        ">ROOT 官网: https://root.cern/\n\n"
        "[外链](https://example.com/a?x=1) "
        "[锚点](#section-1) "
        "[站内](/projects/demo/) "
        "[邮箱](mailto:dev@example.com)\n\n"
        "本地文件 app.py、index.html、README.md 不应自动变成链接。\n"
    )
    res = render_markdown(body)
    assert (
        '<a href="https://root.cern/manual/tmva/" target="_blank" rel="noopener noreferrer">'
        "https://root.cern/manual/tmva/</a>"
    ) in res.html
    assert (
        '<a href="https://root.cern/" target="_blank" rel="noopener noreferrer">https://root.cern/</a>'
    ) in res.html
    assert (
        '<a href="https://example.com/a?x=1" target="_blank" rel="noopener noreferrer">外链</a>'
    ) in res.html
    assert '<a href="#section-1">锚点</a>' in res.html
    assert '<a href="/projects/demo/">站内</a>' in res.html
    assert '<a href="mailto:dev@example.com">邮箱</a>' in res.html
    assert 'href="http://app.py"' not in res.html
    assert 'href="http://index.html"' not in res.html
    assert 'href="http://README.md"' not in res.html


def test_images_csdn_referrerpolicy_lazy_and_fragment() -> None:
    url = "https://i-blog.csdnimg.cn/blog_migrate/659f1b08633aa18d14bfd4c6fe17adad.png#pic_center"
    res = render_markdown(f"![在这里插入图片描述]({url})")
    assert f'src="{url}"' in res.html
    assert 'alt="在这里插入图片描述"' in res.html
    assert 'referrerpolicy="no-referrer"' in res.html
    assert 'loading="lazy"' in res.html
    assert 'decoding="async"' in res.html


def test_latex_inline_display_subscripts_and_code_isolation() -> None:
    body = (
        "信号 $S$、背景 $B$、观测量 $N_{obs}$ 与检验量 $t_{\\mu,test}$、"
        "${\\mu}_{test}$ 和带空格公式 $ t_\\mu = -2\\ln(\\lambda(\\mu)) $、$ CL_s $、"
        "区间 $\\pm2\\sigma$、置信度 $CL_{s+b}$。\n\n"
        "单行公式：\n\n"
        "$$Gini(D)=1-sum(pk**2)$$\n\n"
        "多行公式：\n\n"
        "$$\n"
        "L(n_{obs};\\mu,B) = \\frac{(\\mu S + B)^{n_{obs}}}{n_{obs}!} e^{-(\\mu S + B)}\n"
        "$$\n\n"
        "带编号公式：\n\n"
        "$$E = mc^2$$ (eq-1)\n\n"
        "价格 $5 和 $10 不是公式。\n\n"
        "```bash\n"
        "$ skills add demo\n"
        "echo $HOME $PATH\n"
        "```\n\n"
        "行内代码 `$not_math$` 保持原样。\n"
    )
    res = render_markdown(body)
    assert res.has_math is True
    assert "<em>" not in res.html
    assert '<span class="sf-math sf-math-inline" data-math-display="0">S</span>' in res.html
    assert '<span class="sf-math sf-math-inline" data-math-display="0">B</span>' in res.html
    assert '<span class="sf-math sf-math-inline" data-math-display="0">N_{obs}</span>' in res.html
    assert '<span class="sf-math sf-math-inline" data-math-display="0">t_{\\mu,test}</span>' in res.html
    assert (
        '<span class="sf-math sf-math-inline" data-math-display="0">t_\\mu = -2\\ln(\\lambda(\\mu))</span>'
        in res.html
    )
    assert '<span class="sf-math sf-math-inline" data-math-display="0">CL_s</span>' in res.html
    assert '<div class="sf-math sf-math-display" data-math-display="1">Gini(D)=1-sum(pk**2)</div>' in res.html
    assert "L(n_{obs};\\mu,B)" in res.html
    assert 'id="eq-1"' in res.html
    assert 'class="sf-math-label">(eq-1)</a>' in res.html
    assert "价格 $5 和 $10 不是公式。" in res.html
    assert "$ skills add demo" in res.html
    assert "<code>$not_math$</code>" in res.html


def test_latex_html_escaping_in_math() -> None:
    res = render_markdown("$a < b & c > d$ 和 $$x <script>alert(1)</script> y$$")
    assert res.has_math is True
    assert "<script>" not in res.html
    assert "a &lt; b &amp; c &gt; d" in res.html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in res.html


def test_render_inline_math_for_summaries() -> None:
    plain_html, plain_has_math = render_inline_math("普通摘要 <script>alert(1)</script>")
    assert plain_has_math is False
    assert "<script>" not in plain_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in plain_html

    math_html, math_has_math = render_inline_math(
        "计算 $ t_\\mu = -2\\ln(\\lambda(\\mu)) $ 与 $ CL_s $ 以及 $N$，价格 $5 和 $10"
    )
    assert math_has_math is True
    assert '<span class="sf-math sf-math-inline" data-math-display="0">CL_s</span>' in math_html
    assert '<span class="sf-math sf-math-inline" data-math-display="0">N</span>' in math_html
    assert "$5 和 $10" in math_html
    assert "<div" not in math_html

    empty_html, empty_has_math = render_inline_math("")
    assert (empty_html, empty_has_math) == ("", False)


def test_toc_markers_unicode_anchors_duplicates_and_code_block_preservation() -> None:
    body = (
        "@[TOC](一个Bin的信号强度上限的假设检验上)\n\n"
        "# 一级标题\n\n"
        "## $CL_s$ 方法与 `code`\n\n"
        "### 总结\n\n"
        "### 总结\n\n"
        "#### 四级标题\n\n"
        "##### 五级不入目录\n\n"
        "```markdown\n"
        "@[TOC](代码块内保留)\n"
        "# Python 注释不是标题\n"
        "```\n"
    )
    res = render_markdown(body)
    assert res.toc_title == "一个Bin的信号强度上限的假设检验上"
    assert '@<a href="' not in res.html
    assert "@[TOC](代码块内保留)" in res.html
    assert "# Python 注释不是标题" in res.html
    assert [item.level for item in res.toc] == [1, 2, 3, 3, 4]
    assert [item.depth for item in res.toc] == [0, 1, 2, 2, 3]
    assert [item.text for item in res.toc] == [
        "一级标题",
        "CL_s 方法与 code",
        "总结",
        "总结",
        "四级标题",
    ]
    ids = [item.id for item in res.toc]
    assert len(set(ids)) == len(ids)
    for item in res.toc:
        assert f'id="{item.id}"' in res.html


def test_toc_standard_markers_placeholder_and_empty_headings() -> None:
    r1 = render_markdown("@[TOC](这里写目录标题)\n\n## 第一节\n\n### 子节\n")
    assert r1.toc_title == ""
    assert "@[TOC]" not in r1.html
    assert r1.toc == [
        TocItem(level=2, depth=0, text="第一节", id="第一节"),
        TocItem(level=3, depth=1, text="子节", id="子节"),
    ]

    r2 = render_markdown("[TOC]\n\n[[_TOC_]]\n\n@[TOC]\n\n纯段落无标题")
    assert "[TOC]" not in r2.html
    assert "[[_TOC_]]" not in r2.html
    assert "@[TOC]" not in r2.html
    assert r2.toc == []
    assert r2.toc_title == ""


def test_xss_and_url_scheme_allowlist() -> None:
    png_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    body = (
        "<script>alert(1)</script>\n"
        '<img src=x onerror="alert(1)">\n'
        "[js](javascript:alert(1))\n"
        "[vbs](vbscript:msgbox(1))\n"
        "[file](file:///etc/passwd)\n"
        "[html-data](data:text/html;base64,PHNjcmlwdD4=)\n"
        "[svg-data](data:image/svg+xml;base64,PHN2Zz4=)\n"
        f"[png-link]({png_data})\n"
        f"![ok-png]({png_data})\n"
        "![bad-svg](data:image/svg+xml;base64,PHN2Zz4=)\n"
        "![bad-js](javascript:alert(1))\n"
        "![bad-mailto](mailto:test@example.com)\n"
    )
    res = render_markdown(body)
    assert "<script>" not in res.html
    assert "<img src=x" not in res.html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in res.html
    assert 'href="javascript:' not in res.html
    assert 'href="vbscript:' not in res.html
    assert 'href="file:' not in res.html
    assert 'href="data:' not in res.html
    assert 'src="javascript:' not in res.html
    assert 'src="data:image/svg+xml' not in res.html
    assert 'src="mailto:' not in res.html
    assert f'<img src="{png_data}"' in res.html
    assert "png-link" in res.html


def test_concurrent_render_thread_safety() -> None:
    docs = [
        f"@[TOC](文档{i})\n\n## 相同标题\n\n## 相同标题\n\n" + ("$x_i$" if i % 2 == 0 else "纯文本")
        for i in range(16)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(render_markdown, docs))
    for i, res in enumerate(results):
        assert res.toc_title == f"文档{i}"
        assert [item.id for item in res.toc] == ["相同标题", "相同标题-1"]
        assert res.has_math is (i % 2 == 0)


def test_vendored_katex_offline_integrity_and_woff2_mime() -> None:
    katex_dir = STATIC_DIR / "vendor" / "katex"
    assert (katex_dir / "katex.min.js").is_file()
    assert (katex_dir / "katex.min.css").is_file()
    assert (katex_dir / "LICENSE").is_file()
    assert (katex_dir / "VERSION").read_text().strip() != ""

    css = (katex_dir / "katex.min.css").read_text()
    assert "http://" not in css and "https://" not in css
    woff2_refs = re.findall(r"url\((fonts/[^)]+\.woff2)\)", css)
    assert len(woff2_refs) >= 20
    for rel in woff2_refs:
        assert (katex_dir / rel).is_file(), rel

    with TestClient(app) as client:
        css_resp = client.get("/static/vendor/katex/katex.min.css")
        assert css_resp.status_code == 200
        js_resp = client.get("/static/vendor/katex/katex.min.js")
        assert js_resp.status_code == 200
        font_resp = client.get(f"/static/vendor/katex/{woff2_refs[0]}")
        assert font_resp.status_code == 200
        assert "font/woff2" in font_resp.headers.get("content-type", "")


def test_main_security_middleware_preserves_route_csp() -> None:
    test_app: FastAPI = create_app(app.state.config)

    @test_app.get("/projects/mock-blog/posts/demo")
    def mock_blog_route() -> HTMLResponse:
        return HTMLResponse("<p>ok</p>", headers={"Content-Security-Policy": BLOG_CSP})

    test_app.router.routes.insert(0, test_app.router.routes.pop())

    @test_app.get("/projects/mock-static/index.html")
    def mock_static_route() -> HTMLResponse:
        return HTMLResponse("<p>static</p>", headers={"Content-Security-Policy": SANDBOX_CSP})

    test_app.router.routes.insert(0, test_app.router.routes.pop())

    @test_app.get("/projects/mock-space/")
    def mock_space_route() -> HTMLResponse:
        return HTMLResponse("<p>space</p>")

    test_app.router.routes.insert(0, test_app.router.routes.pop())

    with TestClient(test_app) as client:
        blog_resp = client.get("/projects/mock-blog/posts/demo")
        assert blog_resp.status_code == 200
        assert blog_resp.headers.get("Content-Security-Policy") == BLOG_CSP
        assert blog_resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert blog_resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert blog_resp.headers.get("Referrer-Policy") == "same-origin"

        static_resp = client.get("/projects/mock-static/index.html")
        assert static_resp.status_code == 200
        assert static_resp.headers.get("Content-Security-Policy") == SANDBOX_CSP

        space_resp = client.get("/projects/mock-space/")
        assert space_resp.status_code == 200
        assert "Content-Security-Policy" not in space_resp.headers


def test_blog_http_routes_markdown_math_toc_images_and_csp() -> None:
    csdn_img = "https://i-blog.csdnimg.cn/blog_migrate/659f1b08633aa18d14bfd4c6fe17adad.png#pic_center"
    rich_slug = "skills-安装与记录(trae)"
    rich_body = (
        "@[TOC](【高能物理.ROOT】ROOT,PyROOT,Ubuntu安装)\n\n"
        "# 一、安装步骤\n\n"
        "信号 $S$、背景 $B$、观测量 $N_{obs}$ 与检验量 $t_{\\mu,test}$。\n\n"
        "$$\n"
        "L(n_{obs};\\mu,B) = \\frac{(\\mu S + B)^{n_{obs}}}{n_{obs}!} e^{-(\\mu S + B)}\n"
        "$$\n\n"
        "$$Gini(D)=1-sum(pk**2)$$\n\n"
        "## 1.1 依赖与链接\n\n"
        f"![在这里插入图片描述]({csdn_img})\n\n"
        "[ROOT 官方](https://root.cern/) 与引用[^1]\n\n"
        ">https://root.cern/manual/tmva/\n\n"
        "| 工具 | 状态 |\n"
        "| --- | --- |\n"
        "| ROOT | OK |\n\n"
        "- [x] 安装完成\n"
        "- [ ] 回归验证\n\n"
        "```bash\n"
        "$ skills add demo\n"
        "```\n\n"
        "[^1]: https://root.cern/\n"
    )
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_project_app(client, csrf, "blog", "物理与工程博客").json()["project"]
        plain_blog = create_project_app(client, csrf, "blog", "纯文本博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]

        r1 = client.post(
            f"/api/admin/projects/{pid}/posts",
            json={
                "title": "ROOT 安装与统计笔记",
                "slug": rich_slug,
                "date": "2026-10-05",
                "tags": ["ROOT"],
                "summary": "计算 $ t_\\mu = -2\\ln(\\lambda(\\mu)) $ 与 $ CL_s $",
                "body": rich_body,
            },
            headers=auth_headers(csrf),
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/api/admin/projects/{pid}/posts",
            json={
                "title": "无公式无目录文章",
                "slug": "plain-post",
                "date": "2026-10-01",
                "summary": "普通摘要",
                "body": "这是一篇没有标题也没有数学公式的文章。",
            },
            headers=auth_headers(csrf),
        )
        assert r2.status_code == 200
        r3 = client.post(
            f"/api/admin/projects/{plain_blog['id']}/posts",
            json={"title": "纯文章", "slug": "only-plain", "summary": "纯文字摘要", "body": "无公式"},
            headers=auth_headers(csrf),
        )
        assert r3.status_code == 200

        list_resp = client.get(f"/projects/{slug}/")
        assert list_resp.status_code == 200
        assert list_resp.headers.get("Content-Security-Policy") == BLOG_CSP
        assert "/static/js/theme-init.js" in list_resp.text
        assert "/static/vendor/katex/katex.min.css" in list_resp.text
        assert "/static/vendor/katex/katex.min.js" in list_resp.text
        assert "/static/js/blog_post.js" in list_resp.text
        assert 'class="sf-math sf-math-inline"' in list_resp.text
        assert quote(rich_slug, safe="") in list_resp.text
        assert "<script>" not in list_resp.text
        assert not re.search(r"<(?:script|link)[^>]+https?://", list_resp.text)

        plain_list_resp = client.get(f"/projects/{plain_blog['slug']}/")
        assert plain_list_resp.status_code == 200
        assert plain_list_resp.headers.get("Content-Security-Policy") == BLOG_CSP
        assert "katex.min.css" not in plain_list_resp.text
        assert "katex.min.js" not in plain_list_resp.text
        assert "blog_post.js" not in plain_list_resp.text

        post_resp = client.get(f"/projects/{slug}/posts/{quote(rich_slug, safe='')}")
        assert post_resp.status_code == 200
        assert post_resp.headers.get("Content-Security-Policy") == BLOG_CSP
        assert 'class="blog post-layout has-toc"' in post_resp.text
        assert '<aside class="post-toc"' in post_resp.text
        assert "【高能物理.ROOT】ROOT,PyROOT,Ubuntu安装" in post_resp.text
        assert "data-toc-link" in post_resp.text
        assert '@<a href="' not in post_resp.text
        assert "<em>" not in post_resp.text
        assert '<span class="sf-math sf-math-inline" data-math-display="0">N_{obs}</span>' in post_resp.text
        assert (
            '<div class="sf-math sf-math-display" data-math-display="1">Gini(D)=1-sum(pk**2)</div>'
            in post_resp.text
        )
        assert f'src="{csdn_img}"' in post_resp.text
        assert 'referrerpolicy="no-referrer"' in post_resp.text
        assert 'loading="lazy"' in post_resp.text
        assert (
            '<a href="https://root.cern/" target="_blank" rel="noopener noreferrer">ROOT 官方</a>'
            in post_resp.text
        )
        assert (
            '<a href="https://root.cern/manual/tmva/" target="_blank" rel="noopener noreferrer">'
            "https://root.cern/manual/tmva/</a>"
        ) in post_resp.text
        assert '<div class="table-wrap"><table>' in post_resp.text
        assert 'class="contains-task-list"' in post_resp.text
        assert 'class="footnotes"' in post_resp.text
        assert "$ skills add demo" in post_resp.text
        assert "/static/vendor/katex/katex.min.css" in post_resp.text
        assert "/static/vendor/katex/katex.min.js" in post_resp.text
        assert "/static/js/blog_post.js" in post_resp.text
        assert "<script>" not in post_resp.text
        assert not re.search(r"<(?:script|link)[^>]+https?://", post_resp.text)

        plain_post_resp = client.get(f"/projects/{slug}/posts/plain-post")
        assert plain_post_resp.status_code == 200
        assert plain_post_resp.headers.get("Content-Security-Policy") == BLOG_CSP
        assert "post-toc" not in plain_post_resp.text
        assert "has-toc" not in plain_post_resp.text
        assert "katex.min.css" not in plain_post_resp.text
        assert "katex.min.js" not in plain_post_resp.text
        assert "blog_post.js" not in plain_post_resp.text


def test_no_comments_in_authored_files() -> None:
    authored_py = [Path("app/plugins/blog/markdown.py"), Path("tests/test_blog_markdown.py")]
    for path in authored_py:
        for line in path.read_text().splitlines():
            assert not line.lstrip().startswith("#"), f"comment found in {path}: {line}"
    authored_js = [Path("app/static/js/theme-init.js"), Path("app/static/js/blog_post.js")]
    for path in authored_js:
        text = path.read_text()
        assert "//" not in text and "/*" not in text, f"comment found in {path}"
