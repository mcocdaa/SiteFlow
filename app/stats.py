import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import client_ip, read_session
from app.deps import get_config


def record_visit(db: Session, request: Request, project_id: int | None = None) -> None:
    config = get_config(request)
    session = read_session(config, request)
    if (session and session.get("admin") is True) or request.headers.get("sec-fetch-dest") in {
        "iframe",
        "frame",
        "embed",
        "object",
    }:
        return
    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    identity = f"{today}:{client_ip(request)}:{request.headers.get('user-agent', '')}"
    visitor_hash = hmac.new(config.secret.encode(), identity.encode(), hashlib.sha256).hexdigest()
    scopes = [None] if project_id is None else [None, project_id]
    for scope in scopes:
        params = {"date": today, "scope": -1 if scope is None else scope, "visitor": visitor_hash}
        result = db.execute(
            text("""
            INSERT INTO daily_visitors (date, scope, visitor)
            VALUES (:date, :scope, :visitor)
            ON CONFLICT DO NOTHING RETURNING visitor
        """),
            params,
        )
        uv_inc = int(result.scalar_one_or_none() is not None)
        db.execute(
            text("""
            INSERT INTO daily_stats (date, project_id, pv, uv)
            VALUES (:date, :project_id, 1, :uv_inc)
            ON CONFLICT(date, COALESCE(project_id, -1)) DO UPDATE SET
                pv = pv + 1, uv = uv + :uv_inc
        """),
            {"date": today, "project_id": scope, "uv_inc": uv_inc},
        )
    db.execute(text("DELETE FROM daily_visitors WHERE date < :today"), {"today": today})
    db.commit()


def generate_sparkline(values: list[int], width: int = 120, height: int = 32) -> str:
    if not values:
        values = [0] * 7
    max_val = max(values)
    min_val = min(values)
    val_range = max(max_val - min_val, 1)

    padding_x = 4
    padding_y = 4
    usable_w = width - padding_x * 2
    usable_h = height - padding_y * 2
    step_x = usable_w / max(len(values) - 1, 1)

    points = []
    for i, v in enumerate(values):
        x = padding_x + i * step_x
        ratio = (v - min_val) / val_range if max_val > 0 else 0
        y = (height - padding_y) - ratio * usable_h
        points.append((round(x, 1), round(y, 1)))

    poly_pts = " ".join(f"{x},{y}" for x, y in points)
    area_pts = f"{points[0][0]},{height} " + poly_pts + f" {points[-1][0]},{height}"
    last_x, last_y = points[-1]

    svg = f"""<svg class="sparkline" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="spk-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--accent, #4f46e5)" stop-opacity="0.25" />
      <stop offset="100%" stop-color="var(--accent, #4f46e5)" stop-opacity="0.0" />
    </linearGradient>
  </defs>
  <polygon points="{area_pts}" fill="url(#spk-grad)" />
  <polyline points="{poly_pts}" stroke="var(--accent, #4f46e5)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
  <circle cx="{last_x}" cy="{last_y}" r="3" fill="var(--accent, #4f46e5)" />
</svg>"""
    return svg


def get_7day_stats(db: Session, project_id: int | None = None) -> dict:
    now = datetime.now(UTC)
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    start_date = dates[0]

    if project_id is None:
        sql = text("""
            SELECT date, SUM(pv) as total_pv, SUM(uv) as total_uv
            FROM daily_stats
            WHERE date >= :start_date AND project_id IS NULL
            GROUP BY date
        """)
        rows = db.execute(sql, {"start_date": start_date}).fetchall()
    else:
        sql = text("""
            SELECT date, pv as total_pv, uv as total_uv
            FROM daily_stats
            WHERE date >= :start_date AND project_id = :project_id
        """)
        rows = db.execute(sql, {"start_date": start_date, "project_id": project_id}).fetchall()

    data_map = {row[0]: (row[1] or 0, row[2] or 0) for row in rows}

    pv_series: list[int] = []
    uv_series: list[int] = []
    history: list[dict] = []

    for d in dates:
        pv, uv = data_map.get(d, (0, 0))
        pv_series.append(pv)
        uv_series.append(uv)
        history.append({"date": d[5:], "pv": pv, "uv": uv})

    today_str = dates[-1]
    today_pv, today_uv = data_map.get(today_str, (0, 0))

    return {
        "today_pv": today_pv,
        "today_uv": today_uv,
        "total_pv_7d": sum(pv_series),
        "total_uv_7d": sum(uv_series),
        "sparkline_svg": generate_sparkline(pv_series),
        "history": history,
    }
