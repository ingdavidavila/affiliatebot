"""Command line entry point.

    python -m bot run                 # find deals, then post (what the scheduler calls)
    python -m bot find                # only look for deals
    python -m bot post                # only post approved deals
    python -m bot loop --minutes 30   # run forever (for a server instead of launchd)
    python -m bot import-earnings report.csv --network ebay
    python -m bot status
    python -m bot demo                # build data/demo.db with fake history
    python -m bot dashboard [--demo]  # open the dashboard
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import db
from .config import ROOT, load_config


def _setup_logging(verbose: bool) -> None:
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(log_dir / "bot.log", encoding="utf-8")],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bot", description="Affiliate deal bot")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--config", help="path to config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="find deals then post")
    sub.add_parser("find", help="find deals only")
    sub.add_parser("post", help="post approved deals only")
    p_loop = sub.add_parser("loop", help="run forever")
    p_loop.add_argument("--minutes", type=int, default=30)
    p_imp = sub.add_parser("import-earnings", help="import a network earnings CSV")
    p_imp.add_argument("file")
    p_imp.add_argument("--network", required=True, help="e.g. ebay, amazon, impact")
    sub.add_parser("status", help="print today's numbers")
    sub.add_parser("demo", help="create data/demo.db with fake history")
    p_dash = sub.add_parser("dashboard", help="start the dashboard")
    p_dash.add_argument("--demo", action="store_true", help="use data/demo.db")
    p_dash.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    cfg = load_config(args.config)
    log = logging.getLogger("bot")

    if args.cmd in ("run", "find", "post"):
        from .finder import find_deals
        from .poster import run_poster
        if cfg["dry_run"]:
            log.info("DRY RUN mode: nothing will be posted to X (set dry_run: false in config.yaml)")
        if args.cmd in ("run", "find"):
            find_deals(cfg)
        if args.cmd in ("run", "post"):
            run_poster(cfg)
        return 0

    if args.cmd == "loop":
        from .finder import find_deals
        from .poster import run_poster
        while True:
            try:
                find_deals(cfg)
                run_poster(cfg)
            except Exception:
                log.exception("Cycle failed; will retry next time")
            time.sleep(args.minutes * 60)

    if args.cmd == "import-earnings":
        from .earnings import import_csv
        with db.session(cfg["database"]) as conn, open(args.file, encoding="utf-8-sig") as fh:
            stats = import_csv(conn, fh, args.network)
        print(f"Imported {stats['imported']} rows ({stats['matched']} matched to posts), "
              f"{stats['duplicates']} already imported, {stats['skipped']} skipped.")
        return 0

    if args.cmd == "status":
        from .stats import summary
        with db.session(cfg["database"]) as conn:
            s = summary(conn, days=1)
        print(f"Today: {s['posts']} posts, earned ${s['commission']:.2f}, "
              f"spent ${s['spend']:.2f}, net ${s['net']:.2f}. Queue: {s['queued']} waiting.")
        return 0

    if args.cmd == "demo":
        from .demo_data import seed
        path = str(ROOT / "data" / "demo.db")
        seed(path)
        print(f"Demo database created at {path}. Open it with: python -m bot dashboard --demo")
        return 0

    if args.cmd == "dashboard":
        from dashboard.app import run
        db_path = str(ROOT / "data" / "demo.db") if args.demo else cfg["database"]
        if args.demo and not Path(db_path).exists():
            from .demo_data import seed
            seed(db_path)
        run(cfg, db_path=db_path, demo=args.demo, open_browser=not args.no_browser)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
