import re
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select

from app import stats, store
from app.auth import (
    allow_attempt,
    apply_session,
    check_csrf,
    clear_failures,
    clear_login_failures,
    clear_session,
    create_session,
    csrf_for,
    login_allowed,
    make_project_token,
    new_session_token,
    project_cookie_name,
    read_session,
    record_failure,
    record_login_failure,
    require_admin,
    require_same_origin,
    set_project_cookie,
    verify_password,
    verify_project_password,
    verify_project_token,
)
from app.deps import DbSession, get_config
from app.models import Project
from app.plugins import registry
from app.svg_cover import generate_svg_cover
from app.templating import placeholder_hue, templates

router = APIRouter()

SANDBOX_CSP = "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads"
_SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

MEDIA_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".wasm": "application/wasm",
    ".map": "application/json",
    ".avif": "image/avif",
    ".webmanifest": "application/manifest+json",
}


@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def gallery(request: Request, db: DbSession):
    config = get_config(request)
    session = read_session(config, request)
    stats.record_visit(db, request, project_id=None)
    return templates.TemplateResponse(
        request,
        "gallery.html",
        {
            "site_title": config.site_title,
            "site_description": config.site_description,
            "projects": store.visible_projects(db),
            "hue": placeholder_hue,
            "is_admin": bool(session and session.get("admin") is True),
        },
    )


def safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/admin"


def check_project_access(request: Request, config, project) -> bool:
    if not project.password_hash:
        return True
    session = read_session(config, request)
    if session and session.get("admin") is True:
        return True
    token = request.cookies.get(project_cookie_name(project.slug))
    return bool(token and verify_project_token(config, project.slug, token))


def project_home(request: Request, config, project, db):
    plugin = registry.get(project.type)
    if plugin is not None:
        return plugin.render(request, project, db)
    if not project.entry:
        raise HTTPException(404)
    return RedirectResponse(f"/projects/{project.slug}/{project.entry}", status_code=302)


def find_public_project(db, slug: str):
    project = store.by_slug(db, slug)
    if project is None or project.type == "link" or not store.is_visible(db, project):
        raise HTTPException(404)
    return project


@router.get("/projects/{slug}", include_in_schema=False)
@router.get("/p/{slug}", include_in_schema=False)
def project_root(request: Request, slug: str, db: DbSession):
    config = get_config(request)
    project = find_public_project(db, slug)
    if not check_project_access(request, config, project):
        return templates.TemplateResponse(
            request,
            "project_gate.html",
            {"site_title": config.site_title, "project": project, "error": None},
        )
    stats.record_visit(db, request, project_id=project.id)
    return project_home(request, config, project, db)


@router.post("/projects/{slug}/unlock")
def unlock_project(request: Request, slug: str, db: DbSession, password: str = Form("")):
    config = get_config(request)
    project = find_public_project(db, slug)
    if not project.password_hash:
        return RedirectResponse(f"/projects/{slug}/", status_code=303)
    if not allow_attempt(request, slug):
        return templates.TemplateResponse(
            request,
            "project_gate.html",
            {"site_title": config.site_title, "project": project, "error": "尝试次数过多，请稍后再试"},
            status_code=429,
        )
    if not verify_project_password(project.password_hash, password):
        record_failure(request, slug)
        return templates.TemplateResponse(
            request,
            "project_gate.html",
            {"site_title": config.site_title, "project": project, "error": "密码不正确，请重新输入"},
            status_code=401,
        )
    clear_failures(request, slug)
    token = make_project_token(config, slug)
    response = RedirectResponse(f"/projects/{slug}/", status_code=303)
    set_project_cookie(config, response, slug, token)
    return response


@router.get("/projects/{slug}/{path:path}")
@router.get("/p/{slug}/{path:path}", include_in_schema=False)
def project_file(request: Request, slug: str, path: str, db: DbSession):
    config = get_config(request)
    project = find_public_project(db, slug)

    if not check_project_access(request, config, project):
        is_html_req = not path or path.endswith((".html", ".htm"))
        if is_html_req:
            return templates.TemplateResponse(
                request,
                "project_gate.html",
                {"site_title": config.site_title, "project": project, "error": None},
            )
        raise HTTPException(401, "需要访问密码")

    if not path:
        stats.record_visit(db, request, project_id=project.id)
        return project_home(request, config, project, db)

    if path.strip("/") == "admin":
        return RedirectResponse(f"/admin/projects/{project.id}", status_code=302)

    plugin = registry.get(project.type)
    if plugin is not None:
        response = plugin.route(request, project, path, db)
        if response is None:
            raise HTTPException(404)
        return response

    if project.type not in ("html", "zip", "static"):
        raise HTTPException(404)

    if any(part.startswith(".") for part in Path(path).parts):
        raise HTTPException(404)
    root = (config.data / "projects" / slug).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(404)
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise HTTPException(404)

    stat_res = target.stat()
    etag = f'"{stat_res.st_mtime_ns:x}-{stat_res.st_size:x}"'
    is_html = target.name == "index.html" or target.suffix.lower() in (".html", ".htm")
    cache_control = "no-cache, must-revalidate" if is_html else "public, max-age=86400"

    if is_html:
        stats.record_visit(db, request, project_id=project.id)

    if_none_match = request.headers.get("if-none-match")
    if if_none_match and (if_none_match.strip() == etag or if_none_match.strip() == f"W/{etag}"):
        res = Response(status_code=304)
        res.headers["ETag"] = etag
        res.headers["Cache-Control"] = cache_control
        res.headers["Content-Security-Policy"] = SANDBOX_CSP
        res.headers["X-Frame-Options"] = "SAMEORIGIN"
        res.headers["X-Content-Type-Options"] = "nosniff"
        if not project.password_hash:
            res.headers["Access-Control-Allow-Origin"] = "*"
        return res

    media_type = MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
    if media_type == "text/html":
        media_type += "; charset=utf-8"
    response = FileResponse(target, media_type=media_type)
    response.headers["ETag"] = etag
    response.headers["Content-Security-Policy"] = SANDBOX_CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Cache-Control"] = cache_control
    if not project.password_hash:
        response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@router.get("/media/covers/{name}")
def cover_file(request: Request, name: str):
    config = get_config(request)
    if "/" in name or name.startswith("."):
        raise HTTPException(404)
    covers = (config.data / "media" / "covers").resolve()
    target = (covers / name).resolve()
    if not target.is_relative_to(covers) or not target.is_file():
        raise HTTPException(404)

    stat_res = target.stat()
    etag = f'"{stat_res.st_mtime_ns:x}-{stat_res.st_size:x}"'
    cache_control = "public, max-age=86400"
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and (if_none_match.strip() == etag or if_none_match.strip() == f"W/{etag}"):
        res = Response(status_code=304)
        res.headers["ETag"] = etag
        res.headers["Cache-Control"] = cache_control
        return res

    response = FileResponse(target, media_type="image/webp")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = cache_control
    return response


@router.get("/media/placeholder/{slug}.svg")
def placeholder_svg(slug: str, db: DbSession):
    if not _SLUG_RE.match(slug):
        raise HTTPException(404)
    project = store.by_slug(db, slug)
    title = project.title if project else slug
    ptype = project.type if project else "html"
    svg = generate_svg_cover(slug, title, ptype)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Security-Policy": _SVG_CSP,
        },
    )


@router.get("/api/qrcode")
def qrcode_image(url: str):
    import io

    import qrcode
    import qrcode.image.svg

    if not url:
        raise HTTPException(400, "url parameter is required")
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/login")
@router.get("/admin/login", include_in_schema=False)
def login_page(request: Request):
    config = get_config(request)
    session = read_session(config, request)
    if session is not None and session.get("admin") is True:
        return RedirectResponse("/admin", status_code=303)
    token = new_session_token()
    response = templates.TemplateResponse(
        request,
        "login.html",
        {
            "site_title": config.site_title,
            "csrf": token,
            "error": None,
            "next": safe_next(request.query_params.get("next")),
        },
    )
    apply_session(config, response, token, authenticated=False)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/login")
def login_submit(
    request: Request,
    password: str = Form(""),
    csrf: str = Form(""),
    next_url: str = Form("", alias="next"),
):
    config = get_config(request)
    require_same_origin(request)
    target = safe_next(next_url)
    if not login_allowed(request):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "site_title": config.site_title,
                "csrf": csrf_for(request),
                "error": "尝试次数过多，请稍后再试",
                "next": target,
            },
            status_code=429,
        )
    submitted = request.headers.get("x-csrf-token") or csrf
    if not check_csrf(request, submitted):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "site_title": config.site_title,
                "csrf": csrf_for(request),
                "error": "会话校验失败，请重试",
                "next": target,
            },
            status_code=403,
        )
    if not verify_password(config, password):
        record_login_failure(request)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "site_title": config.site_title,
                "csrf": csrf_for(request),
                "error": "密码不正确",
                "next": target,
            },
            status_code=401,
        )
    clear_login_failures(request)
    response = RedirectResponse(target, status_code=303)
    create_session(config, response)
    return response


@router.post("/logout")
@router.post("/admin/logout", include_in_schema=False)
def logout(request: Request):
    config = get_config(request)
    require_admin(request, config)
    submitted = request.headers.get("x-csrf-token") or ""
    if request.url.path == "/logout" and not check_csrf(request, submitted):
        raise HTTPException(403, "CSRF 校验失败")
    response = RedirectResponse("/", status_code=303)
    clear_session(response)
    return response


_SEARCH_I18N_MAP = {
    "前端架构与基础制品": "Frontend Architecture & Core Artifacts",
    "聚合核心 SPA 控制台、设计系统组件库与全站静态制品": "Aggregated core SPA consoles, design system libraries, and static web bundles",
    "AI 基础架构与微服务空间": "AI Infrastructure & Microservices Space",
    "聚合核心 LLM 推理网关控制台、分布式遥测仪表盘与全站静态制品": "Aggregated LLM inference gateway console, distributed telemetry dashboards, and static web bundles",
    "CloudMonitor 实时遥测控制台": "CloudMonitor Live Telemetry Console",
    "基于 Vite 编译打包的高性能微前端监控仪表盘": "High-performance micro-frontend monitoring dashboard built with Vite",
    "LLM Gateway 实时遥测控制台": "LLM Gateway Live Telemetry Console",
    "多模型路由负载均衡、Token 速率限制与 Prompt 缓存命中率实时监控面板": "Multi-model routing load balancer, token rate limiting, and prompt cache hit-rate dashboard",
    "Playwright 全链路回归测试报告": "Playwright E2E Regression Report",
    "自动化测试全量归档报告，包含 145 个用例轨迹跟踪与真机录屏": "Full automated test archive with 145 trace recordings and viewport captures",
    "CI 构建 #10842 全量归档报告，包含 150 个 E2E 用例轨迹跟踪与多视口断言审计": "CI Build #10842 full archive report with 150 E2E trace recordings and multi-viewport assertions",
    "LLM Agent 推理评测报告": "LLM Agent Reasoning Benchmark Report",
    "多模型推理准确率、Agent 工具调用成功率与 TTFT 延迟全量评测报告": "Multi-model reasoning accuracy, Agent tool-use pass rate, and TTFT latency benchmark report",
    "支付中心微服务 API 规范": "Payment Gateway Microservice API Spec",
    "基于 Redoc / OpenAPI 规范生成的交互式 API 参考手册": "Interactive API reference manual generated from OpenAPI v3.1 specs",
    "2026 Q3 财务审计与预算决算": "2026 Q3 Financial Audit & Budget",
    "核心商业机密项目，已开启专属访问密码保护隔离锁": "Confidential executive report protected by per-project password lock",
    "SiteFlow 开源仓库与文档": "SiteFlow Open-Source Repo & Docs",
    "GitHub 官方代码仓库、更新日志与 Docker 部署指南": "Official GitHub repository, changelog, and Docker deployment guide",
    "基于 Canvas 与 Web Audio 的赛博朋克霓虹 2048 游戏": "Cyberpunk neon 2048 game built with HTML5 Canvas and Web Audio",
    "AI 分析报告": "AI Analysis Report",
    "新空间": "New Space",
    "新建空间": "New Space",
    "简历": "Resume",
    "博客": "Blog",
    "林深 · 首席系统架构师简历": "Lin Shen · Principal Systems Architect Resume",
    "12 年分布式系统、云原生沙箱与高并发微服务架构设计经验": "12+ years in distributed systems, cloud-native sandboxes, and high-concurrency microservices",
    "系统架构与工程实践专栏": "Systems Architecture & Engineering Blog",
    "关于零信任静态托管、安全沙箱隔离与现代前端工程化的深度技术笔记": "In-depth technical notes on zero-trust static hosting, sandbox isolation, and modern frontend engineering",
}


@router.get("/api/search")
def search_projects(request: Request, db: DbSession, q: str = ""):
    config = get_config(request)
    session = read_session(config, request)
    is_admin = bool(session and session.get("admin") is True)
    stmt = select(Project)
    if not is_admin:
        stmt = stmt.where(Project.visible.is_(True))
    candidates = list(db.execute(stmt.order_by(Project.pinned.desc(), Project.created_at.desc())).scalars())
    all_projects = candidates if is_admin else [p for p in candidates if store.is_visible(db, p)]

    query = q.strip().lower()
    results = []
    space_map = {p.id: p.title for p in all_projects if p.type == "space"}

    for p in all_projects:
        match = True
        if query:
            en_title = _SEARCH_I18N_MAP.get(p.title.strip(), "")
            en_desc = _SEARCH_I18N_MAP.get((p.description or "").strip(), "")
            space_title = space_map.get(p.parent_id, "") if p.parent_id else ""
            en_space = _SEARCH_I18N_MAP.get(space_title.strip(), "")
            searchable = (
                f"{p.title} {en_title} {p.slug} {p.description or ''} {en_desc} {p.type} {space_title} {en_space}"
            ).lower()
            match = query in searchable
        if match:
            results.append(
                {
                    "id": p.id,
                    "title": p.title,
                    "slug": p.slug,
                    "description": p.description or "",
                    "type": p.type,
                    "url": p.url if p.type == "link" else f"/projects/{p.slug}/",
                    "space": space_map.get(p.parent_id, "") if p.parent_id else "",
                    "pinned": p.pinned,
                    "is_locked": bool(p.password_hash),
                }
            )
            if len(results) >= 20:
                break

    return JSONResponse(results)
