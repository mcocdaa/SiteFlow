import os
import shutil
from pathlib import Path
from datetime import UTC, datetime, timedelta

# Configure environment
os.environ["ADMIN_PASSWORD"] = "siteflow_admin_2026"
os.environ["COOKIE_SECURE"] = "false"
os.environ["SITE_TITLE"] = "SiteFlow 制品画廊"
os.environ["SITE_DESCRIPTION"] = "现代前端制品、自动化测试报告与微服务文档的安全沙箱展示平台"

data_dir = Path(__file__).resolve().parent.parent / "data"
os.environ["DATA_DIR"] = str(data_dir)

from app.config import Config
from app.main import create_app
from app import store, stats
from app.models import Project
from app.auth import hash_project_password

def seed():
    config = Config.load()
    app = create_app(config)
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

    # 2. Project inside Space: Astro / Vite Dashboard
    proj_dir = config.data / "projects" / "cloud-console"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "index.html").write_text("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>CloudMonitor 控制台</title>
  <style>
    body { font-family: -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px; }
    .card { background: #1e293b; border-radius: 12px; padding: 24px; max-width: 600px; margin: 0 auto; border: 1px solid #334155; }
    h1 { margin-top: 0; color: #38bdf8; }
    .badge { display: inline-block; background: #0284c7; color: #fff; padding: 4px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">Vite + Astro v5</span>
    <h1>CloudMonitor 实时遥测控制台</h1>
    <p>集群健康状态良好，28 个微服务节点在线，响应延迟 12ms。</p>
  </div>
</body>
</html>""", encoding="utf-8")

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
    (pw_dir / "index.html").write_text("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Playwright 自动化测试报告</title>
  <style>
    body { font-family: -apple-system, sans-serif; background: #0b0f19; color: #e2e8f0; margin: 0; padding: 40px; }
    .container { max-width: 800px; margin: 0 auto; }
    .stat-bar { display: flex; gap: 16px; margin: 20px 0; }
    .stat { background: #1e293b; padding: 16px 24px; border-radius: 10px; flex: 1; border-left: 4px solid #10b981; }
    .stat strong { font-size: 24px; color: #10b981; }
    .test-row { background: #1e293b; padding: 12px 16px; border-radius: 8px; margin-bottom: 8px; display: flex; justify-content: space-between; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Playwright 全链路 E2E 自动化回归报告</h1>
    <p>流水线构建 #10842 · 执行耗时 4m 12s · 浏览器引擎: Chromium 124</p>
    <div class="stat-bar">
      <div class="stat"><span>通过用例</span><br><strong>142</strong></div>
      <div class="stat" style="border-left-color: #38bdf8;"><span>跳过</span><br><strong style="color: #38bdf8;">3</strong></div>
      <div class="stat" style="border-left-color: #ef4444;"><span>失败</span><br><strong style="color: #ef4444;">0</strong></div>
    </div>
    <div class="test-row"><span>✓ 用户登录与二要素鉴权流程</span><span style="color:#10b981">通过 (820ms)</span></div>
    <div class="test-row"><span>✓ 大文件分片上传与断点续传</span><span style="color:#10b981">通过 (1.4s)</span></div>
    <div class="test-row"><span>✓ 跨租户数据隔离安全沙箱审计</span><span style="color:#10b981">通过 (640ms)</span></div>
  </div>
</body>
</html>""", encoding="utf-8")

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
    (api_dir / "index.html").write_text("""<!DOCTYPE html>
<html>
<head><title>Payment Gateway API</title><style>body { font-family: monospace; padding: 40px; background: #18181b; color: #fafafa; } .tag { color: #10b981; }</style></head>
<body>
  <h1>Payment Gateway OpenAPI v3.1</h1>
  <p><span class="tag">POST</span> /v1/charges - 创建支付交易</p>
  <p><span class="tag">GET</span> /v1/refunds - 查询退款流水</p>
</body>
</html>""", encoding="utf-8")

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
    (secret_dir / "index.html").write_text("""<!DOCTYPE html>
<html>
<head><title>2026 Q3 财务审计看板</title><style>body { font-family: sans-serif; padding: 40px; background: #0f172a; color: #fff; }</style></head>
<body>
  <h1>2026 第三季度财务审计与预算决算报告</h1>
  <p style="color: #ef4444;">绝密文件：仅限审计委员会与公司高管查阅。</p>
  <p>净利润率同比增长 28.4%，研发投入比 34.2%。</p>
</body>
</html>""", encoding="utf-8")

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

    db.commit()

    # Seed some sample 7-day visit stats for the dashboard sparkline
    now = datetime.now(UTC)
    sample_pvs = [42, 68, 95, 120, 84, 136, 178]
    sample_uvs = [28, 45, 62, 78, 54, 89, 112]
    for i in range(7):
        d_str = (now - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        from sqlalchemy import text
        db.execute(text("""
            INSERT INTO daily_stats (date, project_id, pv, uv)
            VALUES (:date, NULL, :pv, :uv)
            ON CONFLICT(date, COALESCE(project_id, -1)) DO UPDATE SET pv = :pv, uv = :uv
        """), {"date": d_str, "pv": sample_pvs[i], "uv": sample_uvs[i]})
    db.commit()
    db.close()
    print("Seeded successfully!")

if __name__ == "__main__":
    seed()
