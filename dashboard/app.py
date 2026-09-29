"""Local dashboard for the affiliate bot. Runs only on your Mac (127.0.0.1).

Start it with:  python -m bot dashboard        (or double-click "Start Dashboard.command")
"""
from __future__ import annotations

import copy
import secrets
import threading
import webbrowser
from datetime import datetime
from typing import Any

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

from bot import db, stats
from bot.config import load_config, secret
from bot.sources import SOURCE_CLASSES

from .charts import line_chart

REQUIRED_KEYS = {
    "X (posting)": ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"],
    "eBay": ["EBAY_APP_ID", "EBAY_CERT_ID", "EPN_CAMPAIGN_ID"],
    "Amazon (manual deals)": ["AMAZON_ASSOCIATE_TAG"],
}

SETTING_FIELDS = [
    # key, label, type, help
    ("approval_mode", "Approve deals before posting", "bool",
     "When on, new deals wait in the Queue until you approve them."),
    ("min_discount_pct", "Minimum discount (%)", "number", "Ignore deals smaller than this."),
    ("min_price", "Minimum price ($)", "number", "Cheap items earn tiny commissions."),
    ("max_price", "Maximum price ($)", "number", ""),
    ("max_posts_per_day", "Max posts per day", "number", ""),
    ("posts_per_run", "Posts per scheduled run", "number", "How many posts each 30-minute run may make."),
    ("min_minutes_between_posts", "Minutes between posts", "number", "Spacing keeps you clear of X's spam rules."),
    ("daily_budget_usd", "Daily X budget ($)", "number", "Posting stops for the day once this is spent."),
    ("blocked_keywords", "Blocked words", "text", "Comma separated. Deals with these words in the title are skipped."),
    ("hashtags", "Hashtags", "text", ""),
    ("disclosure", "Disclosure", "text", "Required by the FTC on every affiliate post. Keep #ad or similar."),
]

_run_lock = threading.Lock()


def create_app(cfg: dict[str, Any] | None = None, db_path: str | None = None, demo: bool = False) -> Flask:
    cfg = copy.deepcopy(cfg or load_config())
    if db_path:
        cfg["database"] = db_path
    if demo:
        cfg["dry_run"] = True  # demo data can never post for real

    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    app.config["BOT_CFG"] = cfg
    app.config["DEMO"] = demo

    # ---------- helpers ----------
    def conn():
        if "conn" not in g:
            g.conn = db.connect(cfg["database"])
        return g.conn

    @app.teardown_appcontext
    def _close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    def settings() -> dict[str, Any]:
        return db.get_settings(conn(), cfg["settings"])

    def period() -> int:
        try:
            d = int(request.args.get("days", 30))
        except ValueError:
            d = 30
        return d if d in (7, 30, 90, 365) else 30

    def dry_filter() -> bool:
        return bool(cfg["dry_run"])

    @app.before_request
    def _csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        if request.method == "POST" and request.form.get("csrf") != session["csrf"]:
            abort(400, "Form expired, please reload the page and try again.")

    @app.context_processor
    def _inject():
        s = settings()
        last = conn().execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "csrf": session.get("csrf", ""),
            "demo": demo,
            "dry_run": cfg["dry_run"],
            "paused": s["paused"],
            "queued_count": conn().execute("SELECT COUNT(*) FROM deals WHERE status='queued'").fetchone()[0],
            "last_run": dict(last) if last else None,
            "fmt_money": _fmt_money,
            "fmt_time": _fmt_time,
            "nav": request.endpoint,
        }

    # ---------- pages ----------
    @app.get("/")
    def overview():
        days = period()
        s = stats.summary(conn(), days, dry_run=dry_filter())
        rows = stats.daily(conn(), days, dry_run=dry_filter())
        chart = line_chart(rows, [("commission", "Earnings", "--series-1"), ("spend", "X spend + costs", "--series-2")])
        return render_template(
            "overview.html", s=s, chart=chart, rows=rows, days=days,
            cats=stats.by_category(conn(), days, dry_run=dry_filter()),
            top=[p for p in stats.posts_table(conn(), days, 5, dry_run=dry_filter(), order="top") if p["commission"] > 0],
        )

    @app.get("/posts")
    def posts():
        days = period()
        return render_template("posts.html", days=days,
                               posts=stats.posts_table(conn(), days, 500, dry_run=dry_filter(),
                                                       order=request.args.get("order", "recent")),
                               order=request.args.get("order", "recent"))

    @app.get("/queue")
    def queue():
        rows = conn().execute(
            "SELECT * FROM deals WHERE status IN ('queued','approved') "
            "ORDER BY status DESC, discount_pct DESC, found_at DESC LIMIT 300").fetchall()
        return render_template("queue.html",
                               queued=[r for r in rows if r["status"] == "queued"],
                               approved=[r for r in rows if r["status"] == "approved"])

    @app.post("/queue/action")
    def queue_action():
        action = request.form.get("action")
        ids = [int(i) for i in request.form.getlist("id") if i.isdigit()]
        c = conn()
        if action == "approve_all":
            n = c.execute("UPDATE deals SET status='approved' WHERE status='queued'").rowcount
            flash(f"Approved {n} deals.")
        elif action == "skip_all":
            n = c.execute("UPDATE deals SET status='skipped' WHERE status='queued'").rowcount
            flash(f"Skipped {n} deals.")
        elif action in ("approve", "skip", "unapprove") and ids:
            new = {"approve": "approved", "skip": "skipped", "unapprove": "queued"}[action]
            c.executemany("UPDATE deals SET status=? WHERE id=?", [(new, i) for i in ids])
        elif action == "post_now" and ids:
            from bot.poster import post_cost, post_one
            s = settings()
            today = c.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM posts WHERE error IS NULL AND dry_run=? AND posted_at >= ?",
                (1 if cfg["dry_run"] else 0, _today_utc())).fetchone()[0]
            if today + post_cost(cfg) > float(s["daily_budget_usd"]) + 1e-9:
                flash(f"Daily budget reached (${today:.2f} spent). Raise it in Settings to post more today.", "error")
            else:
                result = post_one(c, cfg, s, deal_id=ids[0])
                if result["posted"]:
                    flash(("Dry run: logged the post (nothing sent to X)." if cfg["dry_run"] else "Posted to X."))
                else:
                    flash(f"Posting failed: {result['reason']}", "error")
        c.commit()
        return redirect(url_for("queue"))

    @app.get("/earnings")
    def earnings():
        c = conn()
        rows = c.execute(
            "SELECT e.*, d.title FROM earnings e LEFT JOIN deals d ON d.tracking_id = e.tracking_id "
            "ORDER BY e.event_date DESC, e.id DESC LIMIT 300").fetchall()
        expenses = c.execute("SELECT * FROM expenses ORDER BY date DESC LIMIT 100").fetchall()
        networks = [r[0] for r in c.execute("SELECT DISTINCT network FROM earnings ORDER BY 1")]
        return render_template("earnings.html", rows=rows, expenses=expenses,
                               networks=sorted(set(networks) | {"ebay", "amazon", "impact", "cj"}),
                               today=datetime.now().date().isoformat())

    @app.post("/earnings/import")
    def earnings_import():
        from bot.earnings import import_csv
        f = request.files.get("file")
        network = (request.form.get("network") or "").strip().lower() or "other"
        if not f or not f.filename:
            flash("Choose a CSV file first.", "error")
            return redirect(url_for("earnings"))
        try:
            text = f.read().decode("utf-8-sig", errors="replace")
            st = import_csv(conn(), text, network)
            flash(f"Imported {st['imported']} rows ({st['matched']} matched to your posts). "
                  f"{st['duplicates']} were already imported, {st['skipped']} skipped.")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("earnings"))

    @app.post("/expenses/add")
    def expense_add():
        try:
            amount = float(request.form.get("amount", ""))
        except ValueError:
            flash("Enter an amount like 5.00", "error")
            return redirect(url_for("earnings"))
        conn().execute("INSERT INTO expenses(date, amount_usd, note) VALUES (?,?,?)",
                       (request.form.get("date") or datetime.now().date().isoformat(), amount,
                        (request.form.get("note") or "").strip()[:200]))
        conn().commit()
        flash("Expense added.")
        return redirect(url_for("earnings"))

    @app.post("/expenses/delete")
    def expense_delete():
        conn().execute("DELETE FROM expenses WHERE id=?", (request.form.get("id"),))
        conn().commit()
        return redirect(url_for("earnings"))

    @app.get("/settings")
    def settings_page():
        keys = {group: [(k, bool(secret(k))) for k in names] for group, names in REQUIRED_KEYS.items()}
        sources = [(name, bool((cfg["sources"].get(name) or {}).get("enabled"))) for name in SOURCE_CLASSES]
        return render_template("settings.html", s=settings(), fields=SETTING_FIELDS, keys=keys,
                               sources=sources, db_path=cfg["database"])

    @app.post("/settings")
    def settings_save():
        c = conn()
        for key, _label, kind, _help in SETTING_FIELDS:
            if kind == "bool":
                db.set_setting(c, key, request.form.get(key) == "on")
            elif key in request.form:
                val = request.form[key].strip()
                if kind == "number":
                    try:
                        num = float(val)
                    except ValueError:
                        flash(f"'{val}' isn't a number.", "error")
                        continue
                    if num < 0:
                        flash("Numbers can't be negative.", "error")
                        continue
                    val = str(num)
                db.set_setting(c, key, val)
        if not (request.form.get("disclosure") or "").strip():
            db.set_setting(c, "disclosure", "#ad")
            flash("Disclosure can't be empty, so it was reset to #ad.", "error")
        c.commit()
        flash("Settings saved. The bot uses them on its next run.")
        return redirect(url_for("settings_page"))

    @app.post("/pause")
    def toggle_pause():
        s = settings()
        db.set_setting(conn(), "paused", not s["paused"])
        conn().commit()
        flash("Bot resumed." if s["paused"] else "Bot paused. Nothing will post until you resume.")
        return redirect(request.referrer or url_for("overview"))

    @app.post("/run")
    def run_now():
        if not _run_lock.acquire(blocking=False):
            flash("A run is already in progress.", "error")
            return redirect(request.referrer or url_for("overview"))
        try:
            from bot.finder import find_deals
            from bot.poster import run_poster
            f = find_deals(cfg)
            p = run_poster(cfg)
            msg = f"Found {f['found']} deals, {f['added']} new. Posted {p['posted']}."
            if p["reasons"]:
                msg += " " + "; ".join(p["reasons"])
            flash(msg, "error" if f["errors"] else "info")
        except Exception as exc:
            flash(f"Run failed: {exc}", "error")
        finally:
            _run_lock.release()
        return redirect(request.referrer or url_for("overview"))

    return app


def _today_utc() -> str:
    from datetime import timezone
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).isoformat()


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "–"
    return f"−${abs(v):,.2f}" if v < -0.004 else f"${abs(v):,.2f}"


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return "–"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo:
        dt = dt.astimezone()
    return dt.strftime("%b %-d, %-I:%M %p") if len(iso) > 10 else dt.strftime("%b %-d, %Y")


def run(cfg: dict[str, Any] | None = None, db_path: str | None = None, demo: bool = False,
        open_browser: bool = True) -> None:
    cfg = cfg or load_config()
    app = create_app(cfg, db_path=db_path, demo=demo)
    host, port = cfg["dashboard"]["host"], int(cfg["dashboard"]["port"])
    url = f"http://{host}:{port}/"
    print(f"Dashboard running at {url}  (press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)
