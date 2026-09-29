# Deal Bot

Finds discounted products, builds affiliate links, posts them to X (Twitter), and shows what you're earning in a dashboard on your Mac.

It starts in **dry-run mode** with **fake demo deals**, so you can try everything before adding any API keys or spending money.

```
Deal sources ──► Finder ──► Queue ──► Poster ──► X
(eBay, manual,   (filter,   (you      (limits,
 demo)            dedupe)    approve)  budget)
                     │                   │
                     ▼                   ▼
                  SQLite database ◄── Earnings import (network CSV reports)
                     │
                     ▼
              Dashboard (on your Mac)
```

## 1. Download and set up (one time)

Open **Terminal** and run:

```bash
cd ~
git clone https://github.com/ingdavidavila/affiliatebot.git affiliate-bot
cd affiliate-bot
./scripts/setup_mac.sh
```

> Keep the folder in your home folder (like `~/affiliate-bot`), **not** in Desktop, Documents or Downloads. macOS blocks background jobs from those folders, so the automatic scheduler wouldn't work there.

The setup script creates a private Python environment, installs the 4 libraries the bot needs, and creates your `config.yaml` and `.env` files from the examples.

You need Python 3.9 or newer. If `python3` is missing, install it from [python.org](https://www.python.org/downloads/).

## 2. Look at the dashboard

Double-click **`Start Dashboard.command`** in Finder. The first time, macOS may say it's from an unidentified developer. If so, right-click the file, choose **Open**, then click **Open** again.

It opens in your browser at http://127.0.0.1:8765. Until the bot has made a real run, it shows **made-up demo data** so you can see how it works. To stop it, close the Terminal window.

| Page | What it's for |
|---|---|
| **Overview** | Earnings, X spend, net profit, and a daily chart. Also shows which categories actually sell. |
| **Posts** | Every post with its cost, sales and commission. Click a title to see the exact post text. |
| **Queue** | New deals waiting for approval. Approve, skip, or post one right now. |
| **Earnings** | Import commission reports (CSV) and add other expenses, like a server. |
| **Settings** | Discount threshold, posts per day, daily budget, blocked words, pause switch. |

## 3. Try a run (still safe)

```bash
./.venv/bin/python -m bot run
```

This finds demo deals and puts them in the Queue. Approve some in the dashboard, then run it again. The bot writes the posts and logs them, but because `dry_run: true` is set, nothing goes to X.

## 4. Connect real accounts

Put your keys in `.env` (open it with TextEdit or any editor). Turn sources on or off in `config.yaml`.

**eBay (a good first network: its API doesn't require past sales)**
1. Join [eBay Partner Network](https://partnernetwork.ebay.com). Create a campaign and copy its **Campaign ID** into `EPN_CAMPAIGN_ID`.
2. At [developer.ebay.com](https://developer.ebay.com), create an app and copy the **Production** App ID and Cert ID into `EBAY_APP_ID` and `EBAY_CERT_ID`.
3. In `config.yaml`, set `ebay: enabled: true`, set `demo: enabled: false`, and choose your keywords.

**Amazon (manual for now)**
Amazon's product API requires 10 sales in the last 30 days, so start by pasting deals you find into `data/manual_deals.csv`. Use `data/manual_deals.example.csv` as the template. The bot adds your `AMAZON_ASSOCIATE_TAG` to each link automatically. Then set `manual: enabled: true`.

**X (to post for real)**
1. At [developer.x.com](https://developer.x.com), create an app with **Read and write** permission. Add credits to the account.
2. Copy the API key/secret and the access token/secret into `.env`. If you changed the app's permissions, regenerate the access token afterwards.
3. When the Queue looks good, set `dry_run: false` in `config.yaml`.

Posts cost about **$0.20 each** because they contain a link (X pay-per-use pricing as of Sept 2026). The daily budget in Settings is a hard stop. Keep `costs:` in `config.yaml` updated if X changes its prices.

## 5. Run it automatically

```bash
./scripts/install_scheduler.sh 30     # every 30 minutes while your Mac is awake
./scripts/uninstall_scheduler.sh      # stop
```

Each run looks for new deals, then posts if your limits allow it. The dashboard's **Pause bot** button stops posting without uninstalling anything.

If you'd like it to run 24/7 without your Mac, copy the folder to a small Linux server and run `python -m bot loop --minutes 30` there.

## 6. Track earnings

Every deal gets a unique tracking ID, and the bot puts it in the affiliate link (eBay calls it `customid`). When you download your network's transaction report and import it on the **Earnings** page, each sale is matched to the post that made it. Importing the same file twice doesn't double count anything.

Amazon only reports earnings per store tag, not per link. Amazon sales still count toward your totals, but they appear as "not tied to a post".

Command-line alternative:
```bash
./.venv/bin/python -m bot import-earnings ~/Downloads/report.csv --network ebay
```

## Commands

```bash
./.venv/bin/python -m bot run                 # find + post (what the scheduler runs)
./.venv/bin/python -m bot find                # only look for deals
./.venv/bin/python -m bot post                # only post approved deals
./.venv/bin/python -m bot status              # today's numbers
./.venv/bin/python -m bot dashboard           # open the dashboard
./.venv/bin/python -m bot dashboard --demo    # dashboard with fake data
./.venv/bin/python -m bot demo                # rebuild the fake data
./.venv/bin/python -m unittest discover tests # run the tests
```

## Staying within the rules

- **Disclosure:** the FTC requires every affiliate post to be clearly marked. The bot always adds `#ad` and refuses to post without a disclosure.
- **X automation rules:** don't post duplicates or flood the feed. The bot never reposts the same deal, spaces posts out (60 minutes by default), and varies its wording.
- **Amazon:** don't shorten or cloak Amazon affiliate links, and don't scrape Amazon.

## Adding another network

Create `bot/sources/yournetwork.py` with a class that has `fetch()`, which returns `Deal` objects, and `affiliate_url(deal, tracking_id)`. Register it in `bot/sources/__init__.py` and add a section for it in `config.yaml`. See `bot/sources/ebay.py` for a complete example.

## Project layout

```
bot/
  sources/        demo.py, ebay.py, manual.py (one file per network)
  finder.py       fetch → filter → dedupe → queue
  composer.py     writes the post text (fits 280 chars, always adds #ad)
  poster.py       daily limits, budget, spacing, posting
  x_client.py     X API v2 posting (OAuth 1.0a, no extra libraries)
  earnings.py     CSV report import + matching to posts
  stats.py        numbers for the dashboard
  db.py           SQLite schema
dashboard/        Flask app, templates, styles
scripts/          Mac setup and scheduler
data/             your database and logs (not uploaded to GitHub)
```
