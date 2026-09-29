"""Server-rendered SVG charts (no JavaScript libraries or internet needed)."""
from __future__ import annotations

import math
from datetime import date
from html import escape
from typing import Any

W, H = 760, 260
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 16, 32


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


def _money(v: float) -> str:
    return f"${v:,.0f}" if abs(v) >= 100 or v == int(v) else f"${v:,.2f}"


def line_chart(rows: list[dict[str, Any]], series: list[tuple[str, str, str]]) -> str:
    """rows: [{'date': 'YYYY-MM-DD', key: value, ...}]; series: [(key, label, css_var)].

    One shared dollar axis (both series are dollars), 2px lines, hover tooltip
    via per-day hit areas that app.js reads.
    """
    if not rows:
        return '<p class="muted">No data yet.</p>'
    n = len(rows)
    top = _nice_max(max(max(r[k] for r in rows) for k, _, _ in series))
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def x(i: int) -> float:
        return PAD_L + (pw * i / (n - 1) if n > 1 else pw / 2)

    def y(v: float) -> float:
        return PAD_T + ph - (v / top) * ph

    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Daily earnings and spend">']
    for i in range(5):  # recessive grid + y labels
        v = top * i / 4
        yy = y(v)
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="axis" x="{PAD_L - 8}" y="{yy + 4:.1f}" text-anchor="end">{_money(v)}</text>')
    step = max(1, n // 6)  # ~6 x labels
    for i in range(0, n, step):
        d = date.fromisoformat(rows[i]["date"])
        parts.append(f'<text class="axis" x="{x(i):.1f}" y="{H - 10}" text-anchor="middle">{d.strftime("%b %-d")}</text>')
    for key, label, var in series:
        pts = " ".join(f"{x(i):.1f},{y(r[key]):.1f}" for i, r in enumerate(rows))
        parts.append(f'<polyline class="series" style="stroke:var({var})" points="{pts}"/>')
    # crosshair + hit areas
    parts.append(f'<line class="crosshair" x1="0" x2="0" y1="{PAD_T}" y2="{PAD_T + ph}" visibility="hidden"/>')
    band = pw / max(n - 1, 1)
    for i, r in enumerate(rows):
        data = " ".join(f'data-{k}="{r[k]:.2f}"' for k, _, _ in series)
        parts.append(
            f'<rect class="hit" x="{x(i) - band / 2:.1f}" y="{PAD_T}" width="{band:.1f}" height="{ph}" '
            f'data-x="{x(i):.1f}" data-date="{escape(r["date"])}" {data}/>'
        )
    parts.append("</svg>")
    legend = "".join(
        f'<span class="key"><i style="background:var({var})"></i>{escape(label)}</span>' for _, label, var in series
    )
    labels = "|".join(f"{k}:{label}" for k, label, _ in series)
    return (f'<div class="chart-wrap" data-series="{escape(labels)}">'
            f'<div class="legend">{legend}</div>{"".join(parts)}<div class="tip" hidden></div></div>')
