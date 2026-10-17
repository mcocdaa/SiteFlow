import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Configure environment
os.environ["ADMIN_PASSWORD"] = "siteflow_admin_2026"
os.environ["COOKIE_SECURE"] = "false"
os.environ["SITE_TITLE"] = "SiteFlow 制品画廊"
os.environ["SITE_DESCRIPTION"] = "现代前端制品、自动化测试报告与微服务文档的安全沙箱展示平台"

data_dir = Path(__file__).resolve().parent.parent / "data"
os.environ["DATA_DIR"] = str(data_dir)

from app import store
from app.auth import hash_project_password
from app.config import Config
from app.main import create_app
from app.models import Project


def seed():
    config = Config.load()
    create_app(config)
    session_maker = store.init(config)
    db = session_maker()

    # Clear existing projects for a clean demo
    db.query(Project).delete()
    db.commit()

    # 1. Space: 前端架构与基础制品
    space1 = Project(
        slug="frontend-infra",
        type="space",
        title="前端架构与基础制品",
        description="聚合核心 SPA 控制台、设计系统组件库与全站静态制品",
        content='{"accent": "#0ea5e9", "font_family": "sans", "radius_card": "14px"}',
        pinned=True,
        sort_order=0,
    )
    db.add(space1)
    db.commit()

    bilingual_script = """  <script>
    (function () {
      function applyArtifactLang(rawLang) {
        var isEn = String(rawLang || "").toLowerCase().indexOf("en") === 0;
        document.documentElement.lang = isEn ? "en" : "zh-CN";
        var docTitle = document.documentElement.getAttribute(isEn ? "data-title-en" : "data-title-zh");
        if (docTitle) document.title = docTitle;
        document.querySelectorAll("[data-zh][data-en]").forEach(function (el) {
          el.textContent = el.getAttribute(isEn ? "data-en" : "data-zh");
        });
      }
      var params = new URLSearchParams(window.location.search);
      var initLang = params.get("lang") || "zh-CN";
      applyArtifactLang(initLang);
      window.addEventListener("message", function (e) {
        if (e.data && e.data.type === "siteflow:lang") {
          applyArtifactLang(e.data.lang);
        }
      });
    })();
  </script>"""

    # 2. Project inside Space: Astro / Vite Dashboard
    proj_dir = config.data / "projects" / "cloud-console"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "index.html").write_text(
        f"""<!DOCTYPE html>
<html lang="zh-CN" data-title-zh="CloudMonitor 控制台" data-title-en="CloudMonitor Telemetry Console">
<head>
  <meta charset="utf-8">
  <title>CloudMonitor 控制台</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px; }}
    .card {{ background: #1e293b; border-radius: 12px; padding: 24px; max-width: 600px; margin: 0 auto; border: 1px solid #334155; }}
    h1 {{ margin-top: 12px; color: #38bdf8; }}
    .badge {{ display: inline-block; background: #0284c7; color: #fff; padding: 4px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">Vite + Astro v5</span>
    <h1 data-zh="CloudMonitor 实时遥测控制台" data-en="CloudMonitor Live Telemetry Console">CloudMonitor 实时遥测控制台</h1>
    <p data-zh="集群健康状态良好，28 个微服务节点在线，响应延迟 12ms。" data-en="Cluster health is optimal: 28 microservice nodes online, p95 latency 12ms.">集群健康状态良好，28 个微服务节点在线，响应延迟 12ms。</p>
  </div>
{bilingual_script}
</body>
</html>""",
        encoding="utf-8",
    )

    proj1 = Project(
        slug="cloud-console",
        type="html",
        parent_id=space1.id,
        title="CloudMonitor 实时遥测控制台",
        description="基于 Vite 编译打包的高性能微前端监控仪表盘",
        entry="index.html",
        pinned=True,
        sort_order=0,
    )
    db.add(proj1)

    # 3. Project: Playwright E2E 自动化测试报告
    pw_dir = config.data / "projects" / "playwright-e2e-report"
    pw_dir.mkdir(parents=True, exist_ok=True)
    (pw_dir / "index.html").write_text(
        f"""<!DOCTYPE html>
<html lang="zh-CN" data-title-zh="Playwright 自动化测试报告" data-title-en="Playwright E2E Regression Report">
<head>
  <meta charset="utf-8">
  <title>Playwright 自动化测试报告</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; background: #0b0f19; color: #e2e8f0; margin: 0; padding: 40px; }}
    .container {{ max-width: 800px; margin: 0 auto; }}
    .stat-bar {{ display: flex; gap: 16px; margin: 20px 0; }}
    .stat {{ background: #1e293b; padding: 16px 24px; border-radius: 10px; flex: 1; border-left: 4px solid #10b981; }}
    .stat strong {{ font-size: 24px; color: #10b981; }}
    .test-row {{ background: #1e293b; padding: 12px 16px; border-radius: 8px; margin-bottom: 8px; display: flex; justify-content: space-between; }}
  </style>
</head>
<body>
  <div class="container">
    <h1 data-zh="Playwright 全链路 E2E 自动化回归报告" data-en="Playwright Full-Stack E2E Regression Report">Playwright 全链路 E2E 自动化回归报告</h1>
    <p data-zh="流水线构建 #10842 · 执行耗时 4m 12s · 浏览器引擎: Chromium 124" data-en="Pipeline Build #10842 · Duration 4m 12s · Browser Engine: Chromium 124">流水线构建 #10842 · 执行耗时 4m 12s · 浏览器引擎: Chromium 124</p>
    <div class="stat-bar">
      <div class="stat"><span data-zh="通过用例" data-en="Passed">通过用例</span><br><strong>142</strong></div>
      <div class="stat" style="border-left-color: #38bdf8;"><span data-zh="跳过" data-en="Skipped">跳过</span><br><strong style="color: #38bdf8;">3</strong></div>
      <div class="stat" style="border-left-color: #ef4444;"><span data-zh="失败" data-en="Failed">失败</span><br><strong style="color: #ef4444;">0</strong></div>
    </div>
    <div class="test-row"><span data-zh="✓ 用户登录与二要素鉴权流程" data-en="✓ User Sign-In & 2FA Authentication Flow">✓ 用户登录与二要素鉴权流程</span><span style="color:#10b981" data-zh="通过 (820ms)" data-en="PASSED (820ms)">通过 (820ms)</span></div>
    <div class="test-row"><span data-zh="✓ 大文件分片上传与断点续传" data-en="✓ Chunked File Upload & Resumable Transfer">✓ 大文件分片上传与断点续传</span><span style="color:#10b981" data-zh="通过 (1.4s)" data-en="PASSED (1.4s)">通过 (1.4s)</span></div>
    <div class="test-row"><span data-zh="✓ 跨租户数据隔离安全沙箱审计" data-en="✓ Multi-Tenant CSP Sandbox Isolation Audit">✓ 跨租户数据隔离安全沙箱审计</span><span style="color:#10b981" data-zh="通过 (640ms)" data-en="PASSED (640ms)">通过 (640ms)</span></div>
  </div>
{bilingual_script}
</body>
</html>""",
        encoding="utf-8",
    )

    proj2 = Project(
        slug="playwright-e2e-report",
        type="html",
        title="Playwright 全链路回归测试报告",
        description="自动化测试全量归档报告，包含 145 个用例轨迹跟踪与真机录屏",
        entry="index.html",
        pinned=True,
        sort_order=1,
    )
    db.add(proj2)

    # 4. Project: API 文档 (Swagger / OpenAPI)
    api_dir = config.data / "projects" / "payment-api-docs"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "index.html").write_text(
        f"""<!DOCTYPE html>
<html lang="zh-CN" data-title-zh="Payment Gateway API 规范" data-title-en="Payment Gateway OpenAPI v3.1">
<head><meta charset="utf-8"><title>Payment Gateway API</title><style>body {{ font-family: monospace; padding: 40px; background: #18181b; color: #fafafa; }} .tag {{ color: #10b981; font-weight: 700; }}</style></head>
<body>
  <h1 data-zh="Payment Gateway OpenAPI v3.1 接口规范" data-en="Payment Gateway OpenAPI v3.1 Reference">Payment Gateway OpenAPI v3.1 接口规范</h1>
  <p><span class="tag">POST</span> /v1/charges - <span data-zh="创建支付交易" data-en="Create a payment charge">创建支付交易</span></p>
  <p><span class="tag">GET</span> /v1/refunds - <span data-zh="查询退款流水" data-en="List refund transactions">查询退款流水</span></p>
{bilingual_script}
</body>
</html>""",
        encoding="utf-8",
    )

    proj3 = Project(
        slug="payment-api-docs",
        type="html",
        title="支付中心微服务 API 规范",
        description="基于 Redoc / OpenAPI 规范生成的交互式 API 参考手册",
        entry="index.html",
        sort_order=2,
    )
    db.add(proj3)

    # 5. Project: 密码保护的项目 (2026 Q3 财务审计看板)
    secret_dir = config.data / "projects" / "q3-audit-dashboard"
    secret_dir.mkdir(parents=True, exist_ok=True)
    (secret_dir / "index.html").write_text(
        f"""<!DOCTYPE html>
<html lang="zh-CN" data-title-zh="2026 Q3 财务审计看板" data-title-en="2026 Q3 Financial Audit Dashboard">
<head><meta charset="utf-8"><title>2026 Q3 财务审计看板</title><style>body {{ font-family: sans-serif; padding: 40px; background: #0f172a; color: #fff; }}</style></head>
<body>
  <h1 data-zh="2026 第三季度财务审计与预算决算报告" data-en="2026 Q3 Financial Audit & Budget Report">2026 第三季度财务审计与预算决算报告</h1>
  <p style="color: #ef4444;" data-zh="绝密文件：仅限审计委员会与公司高管查阅。" data-en="CONFIDENTIAL: Restricted to Audit Committee & Executive Leadership.">绝密文件：仅限审计委员会与公司高管查阅。</p>
  <p data-zh="净利润率同比增长 28.4%，研发投入比 34.2%。" data-en="Net profit margin grew +28.4% YoY; R&D investment ratio at 34.2%.">净利润率同比增长 28.4%，研发投入比 34.2%。</p>
{bilingual_script}
</body>
</html>""",
        encoding="utf-8",
    )

    proj4 = Project(
        slug="q3-audit-dashboard",
        type="html",
        title="2026 Q3 财务审计与预算决算",
        description="核心商业机密项目，已开启专属访问密码保护隔离锁",
        entry="index.html",
        password_hash=hash_project_password("siteflow2026"),
        sort_order=3,
    )
    db.add(proj4)

    # 6. External Link
    proj5 = Project(
        slug="github-siteflow",
        type="link",
        title="SiteFlow 开源仓库与文档",
        description="GitHub 官方代码仓库、更新日志与 Docker 部署指南",
        url="https://github.com/mcocdaa/SiteFlow",
        sort_order=4,
    )
    db.add(proj5)

    # 7. 2048 Neon Game
    neon_dir = config.data / "projects" / "2048-neon"
    neon_dir.mkdir(parents=True, exist_ok=True)
    (neon_dir / "index.html").write_text(
        f"""<!DOCTYPE html>
<html lang="zh-CN" data-title-zh="2048 Neon 赛博朋克版" data-title-en="2048 Neon Cyberpunk Edition">
<head>
  <meta charset="utf-8">
  <title>2048 Neon</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; background: #090d16; color: #f8fafc; margin: 0; padding: 32px; text-align: center; }}
    h1 {{ color: #38bdf8; margin: 0 0 8px; text-shadow: 0 0 14px rgba(56,189,248,.45); }}
    p {{ color: #94a3b8; margin: 0 0 20px; font-size: 14px; }}
    .board {{ display: grid; grid-template-columns: repeat(4, 68px); gap: 10px; justify-content: center; background: #1e293b; padding: 14px; border-radius: 14px; width: max-content; margin: 0 auto; border: 1px solid #334155; }}
    .tile {{ width: 68px; height: 68px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 20px; background: #0f172a; color: #38bdf8; box-shadow: inset 0 0 10px rgba(56,189,248,.2); }}
    .tile.hi {{ background: #0284c7; color: #fff; box-shadow: 0 0 14px rgba(56,189,248,.5); }}
  </style>
</head>
<body>
  <h1 data-zh="2048 Neon · 赛博矩阵" data-en="2048 Neon · Cyber Matrix">2048 Neon · 赛博矩阵</h1>
  <p data-zh="使用方向键或滑动合并霓虹能量块 · 当前最高分: 16,480" data-en="Use arrow keys or swipe to merge neon tiles · Best Score: 16,480">使用方向键或滑动合并霓虹能量块 · 当前最高分: 16,480</p>
  <div class="board">
    <div class="tile">2</div><div class="tile">4</div><div class="tile">16</div><div class="tile hi">64</div>
    <div class="tile"></div><div class="tile">8</div><div class="tile hi">128</div><div class="tile hi">512</div>
    <div class="tile">4</div><div class="tile">32</div><div class="tile hi">256</div><div class="tile hi">2048</div>
    <div class="tile">2</div><div class="tile"></div><div class="tile">8</div><div class="tile">16</div>
  </div>
{bilingual_script}
</body>
</html>""",
        encoding="utf-8",
    )
    proj_neon = Project(
        slug="2048-neon",
        type="html",
        title="2048-neon",
        description="基于 Canvas 与 Web Audio 的赛博朋克霓虹 2048 游戏",
        entry="index.html",
        pinned=True,
        sort_order=5,
    )
    db.add(proj_neon)

    # 8. Resume App (/p/resume)
    import json

    resume_data = {
        "basics": {
            "name": "林深",
            "label": "首席系统架构师",
            "image": "",
            "email": "linshen@nebula-tech.io",
            "phone": "+86 138-0013-8000",
            "url": "https://linshen.dev",
            "summary": "专注于大规模分布式系统、安全沙箱隔离引擎与高吞吐微服务网关架构，主导过多款开源云原生基础设施产品。",
            "location": {"city": "上海", "region": "中国", "countryCode": "CN"},
            "profiles": [
                {"network": "GitHub", "username": "linshen", "url": "https://github.com/linshen"},
            ],
        },
        "work": [
            {
                "name": "星云科技",
                "position": "首席系统架构师",
                "startDate": "2022-03",
                "endDate": "至今",
                "url": "https://nebula-tech.io",
                "summary": "负责下一代多租户云原生制品托管与零信任安全沙箱平台架构设计。",
                "highlights": [
                    "主导设计零信任 CSP 沙箱与 ZipBomb 防御引擎，日均拦截 10 万+ 异常制品上传",
                    "构建高并发边缘静态分发网关，将全球 P99 响应延迟从 48ms 降至 9ms",
                ],
            },
            {
                "name": "极光云基础设施",
                "position": "高级分布式系统工程师",
                "startDate": "2018-07",
                "endDate": "2022-02",
                "url": "https://aurora-cloud.io",
                "summary": "核心参与容器调度网络与分布式遥测存储引擎研发。",
                "highlights": [
                    "研发高吞吐时序遥测聚合管道，支撑每秒 500 万指标写入与亚秒级查询",
                ],
            },
        ],
        "education": [
            {
                "institution": "上海交通大学",
                "area": "计算机科学与技术",
                "studyType": "硕士",
                "startDate": "2015-09",
                "endDate": "2018-06",
            }
        ],
        "projects": [
            {
                "name": "SiteFlow 安全沙箱制品引擎",
                "url": "https://github.com/mcocdaa/SiteFlow",
                "description": "零构建、内联 SVG 视觉封面与单进程 SQLite WAL 驱动的静态制品托管画廊。",
                "highlights": [
                    "实现多编码嗅探转码、流式解压审计与空间独立主题定制系统",
                ],
                "keywords": ["FastAPI", "SQLite WAL", "CSP 沙箱"],
            }
        ],
        "skills": [
            {
                "name": "系统架构与后端",
                "keywords": ["Python", "Rust", "Go", "FastAPI", "分布式系统"],
            },
            {
                "name": "云原生与安全隔离",
                "keywords": ["Docker", "Kubernetes", "CSP 沙箱", "零信任架构"],
            },
        ],
    }
    proj_resume = Project(
        slug="resume",
        type="resume",
        title="林深 · 首席系统架构师简历",
        description="12 年分布式系统、云原生沙箱与高并发微服务架构设计经验",
        content=json.dumps(resume_data, ensure_ascii=False),
        sort_order=6,
    )
    db.add(proj_resume)

    # 9. Blog App (/p/blog)
    blog_data = {
        "title": "系统架构与工程实践专栏",
        "description": "关于零信任静态托管、安全沙箱隔离与现代前端工程化的深度技术笔记",
        "posts": [
            {
                "slug": "sandbox-architecture",
                "title": "为什么现代静态制品托管需要零信任 CSP 沙箱与流式审计",
                "date": "2026-10-15",
                "tags": ["架构", "安全沙箱", "工程实践"],
                "summary": "深入剖析多租户 HTML 与 ZIP 制品托管中的 XSS 隔离、ZipBomb 防御以及编码自愈机制。",
                "body": "在托管第三方或 CI 流水线自动生成的静态 HTML 制品时，传统的静态文件服务器往往面临两大核心风险：跨站脚本执行（XSS）污染主站会话与恶意压缩包（ZipBomb / 路径穿越）耗尽磁盘资源。\n\n### 1. 严格的 CSP Sandbox 隔离\n\n通过为静态制品响应头注入独立的 Content-Security-Policy 沙箱策略，我们可以在允许制品内部交互脚本正常运行的同时，阻断其对主站 Cookie 与管理员会话的读取权限。\n\n### 2. 流式解压与膨胀比审计\n\n在解压阶段对单文件膨胀比、总解压字节数与目录 Inode 上限进行实时熔断校验，确保任何异常压缩包在落盘前即被安全拦截。",
            },
            {
                "slug": "sqlite-wal-performance",
                "title": "单机十万级并发读写的 SQLite WAL 调优实践",
                "date": "2026-10-08",
                "tags": ["数据库", "性能优化", "架构"],
                "summary": "无需引入沉重的外部数据库集群，通过 WAL 模式与内存映射实现微秒级元数据检索与 PV/UV 统计。",
                "body": "对于轻量级自托管平台而言，维护独立的外部数据库实例往往带来额外的运维负担。通过合理配置 SQLite 的 WAL 日志模式与同步级别，单机即可轻松支撑高并发读与高频统计写入。\n\n### 核心调优参数\n\n- 开启 WAL 日志模式实现读写并发不阻塞\n- 使用确定性唯一索引实现每日 PV / UV 的幂等原子累加",
            },
        ],
    }
    proj_blog = Project(
        slug="blog",
        type="blog",
        title="系统架构与工程实践专栏",
        description="关于零信任静态托管、安全沙箱隔离与现代前端工程化的深度技术笔记",
        content=json.dumps(blog_data, ensure_ascii=False),
        sort_order=7,
    )
    db.add(proj_blog)

    db.commit()

    # Seed some sample 7-day visit stats for the dashboard sparkline
    now = datetime.now(UTC)
    sample_pvs = [42, 68, 95, 120, 84, 136, 178]
    sample_uvs = [28, 45, 62, 78, 54, 89, 112]
    for i in range(7):
        d_str = (now - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        from sqlalchemy import text

        db.execute(
            text("""
            INSERT INTO daily_stats (date, project_id, pv, uv)
            VALUES (:date, NULL, :pv, :uv)
            ON CONFLICT(date, COALESCE(project_id, -1)) DO UPDATE SET pv = :pv, uv = :uv
        """),
            {"date": d_str, "pv": sample_pvs[i], "uv": sample_uvs[i]},
        )
    db.commit()
    db.close()
    print("Seeded successfully!")


if __name__ == "__main__":
    seed()
