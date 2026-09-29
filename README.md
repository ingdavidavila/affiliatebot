# Deal Bot

Finds discounted products, builds affiliate links, posts them to X (Twitter), pulls in your commissions, and shows what you're earning in a dashboard on your Mac. Once it's set up, it runs on **autopilot**, with no approving or uploading needed.

It starts in **dry-run mode** with **fake demo deals**, so you can try everything before adding any API keys or spending money.

```
 Deal databases                       Autopilot                         Out
 ─────────────                        ─────────                         ───
 Keepa (Amazon price history) ──┐     filter → dedupe → score           ┌──► X
 eBay Browse API ───────────────┼──►  (discount, price, category   ─────┤
 manual CSV (optional) ─────────┘      rotation, past sales)            │
                                            │                           │
                                            ▼                           │
 eBay Partner Network report API ───►  SQLite database  ◄───────────────┘
 (commissions, synced every 6 h)            │
                                            ▼
                                   Dashboard (on your Mac)
```

## What runs without you

| Step | How it's automated |
|---|---|
| **Finding deals** | Keepa's Amazon price-history database finds items whose price dropped vs. their 90-day average. The eBay Browse API finds items eBay marks as discounted. |
| **Choosing what to post** | Every deal gets a score from its discount and price. The score also favors categories that have **actually earned you money** (learned from your own sales), and it avoids repeating a category from the last 3 posts. |
| **Posting** | The best deal is posted within your daily post limit and budget, spaced out (60 min by default). Deals older than 24 h are dropped, because prices change. |
| **Recovering from problems** | If posting fails 3 times in a row, the bot waits 6 hours and then retries on its own. If one source is down, the others keep working. |
| **Tracking earnings** | eBay commissions are pulled from eBay Partner Network's API every 6 hours. Each sale is matched to the post that made it, and revised amounts are updated automatically. |

The one thing that isn't automatic is Amazon earnings. Amazon has no earnings API, so Amazon commissions only show up if you import Amazon's report now and then (optional). Your Amazon payouts aren't affected either way.

## 1. Download and set up (one time)

Open **Terminal** and run:

```bash
cd ~
git clone https://github.com/ingdavidavila/affiliatebot.git affiliate-bot
cd affiliate-bot
./scripts/setup_mac.sh
```

> Keep the folder in your home folder (like `~/affiliate-bot`), **not** in Desktop, Documents or Downloads. macOS blocks background jobs from those folders, so the scheduler wouldn't work there.

You need Python 3.9 or newer. If `python3` is missing, install it from [python.org](https://www.python.org/downloads/).

## 2. Look at the dashboard

Double-click **`Start Dashboard.command`** in Finder. The first time, macOS may say it's from an unidentified developer. If so, right-click the file, choose **Open**, then click **Open** again.

It opens at http://127.0.0.1:8765. Until the bot has made a real run, it shows **made-up demo data**. To stop it, close the Terminal window.

| Page | What it's for |
|---|---|
| **Overview** | Earnings, X spend, net profit, a daily chart, and which categories actually sell. |
| **Posts** | Every post with its cost, sales and commission. |
| **Queue** | Deals lined up to post next. If you turn off autopilot, you can approve deals by hand here. |
| **Earnings** | Automatic sync status and a **Sync now** button. You can also import reports by hand and add other expenses. |
| **Settings** | Posting rules, autopilot options, pause switch, API key status, and when each automatic step last ran. |

## 3. Try a run (still safe)

```bash
./.venv/bin/python -m bot run
```

This finds demo deals, picks the best one, and writes the post. Because `dry_run: true` is set, nothing goes to X.

## 4. Connect the data sources

Put your keys in `.env` (open it with TextEdit or any editor). Turn sources on in `config.yaml`, and set `demo: enabled: false` once a real source works.

**Amazon deals via Keepa**
1. Join [Amazon Associates](https://affiliate-program.amazon.com) and copy your store tag (like `yourname-20`) into `AMAZON_ASSOCIATE_TAG`.
2. Get a Keepa API plan at [keepa.com](https://keepa.com/#!api) (paid) and copy the key into `KEEPA_API_KEY`. One scan costs 5 tokens for up to 150 deals.
3. In `config.yaml`, set `keepa: enabled: true`.

Posts for Amazon deals say how far the price dropped (e.g. "41% below its 90-day average") but don't quote a price. Amazon's rules limit showing prices that didn't come from Amazon's own API. I'm not a lawyer, so read Amazon's current Program Policies yourself.

**eBay deals**
1. Join [eBay Partner Network](https://partnernetwork.ebay.com) and copy a campaign's **Campaign ID** into `EPN_CAMPAIGN_ID`.
2. At [developer.ebay.com](https://developer.ebay.com), create an app and copy the Production **App ID** and **Cert ID** into `EBAY_APP_ID` and `EBAY_CERT_ID`.
3. In `config.yaml`, set `ebay: enabled: true` and pick your keywords.

**eBay earnings (automatic)**
1. In the eBay Partner Network portal, find your API credentials (**Account SID** and **Auth Token**). Copy them into `EPN_ACCOUNT_SID` and `EPN_AUTH_TOKEN`.
2. In `config.yaml`, set `earnings_sync: networks: [ebay]`.
3. Check it works: `./.venv/bin/python -m bot sync-earnings`

**X (to post for real)**
1. At [developer.x.com](https://developer.x.com), create an app with **Read and write** permission and add credits.
2. Copy the API key/secret and access token/secret into `.env`. Regenerate the access token if you changed permissions.
3. Watch a few dry runs on the Queue and Posts pages. When it looks right, set `dry_run: false` in `config.yaml`.

Posts cost about **$0.20 each** because they contain a link (X pay-per-use pricing, Sept 2026). The daily budget in Settings is a hard stop.

## 5. Turn on autopilot

```bash
./scripts/install_scheduler.sh 30     # every 30 minutes while your Mac is awake
./scripts/uninstall_scheduler.sh      # stop
```

Each run does three things: finds deals, posts the best one if your limits allow, and syncs earnings if 6 hours have passed since the last sync. **Pause bot** in the dashboard stops posting at any time.

To run 24/7 without your Mac, copy the folder to a small Linux server and run `python -m bot loop --minutes 30` there.

Prefer to review deals first? In Settings, turn on **Approve deals by hand before posting**.

## Commands

```bash
./.venv/bin/python -m bot run                 # find + post + sync (what the scheduler runs)
./.venv/bin/python -m bot find                # only look for deals
./.venv/bin/python -m bot post                # only post
./.venv/bin/python -m bot sync-earnings       # pull commissions now
./.venv/bin/python -m bot import-earnings report.csv --network amazon
./.venv/bin/python -m bot status              # today's numbers
./.venv/bin/python -m bot dashboard           # open the dashboard
./.venv/bin/python -m bot dashboard --demo    # dashboard with fake data
./.venv/bin/python -m unittest discover tests # run the tests
```

## Staying within the rules

- **Disclosure:** the FTC requires every affiliate post to be clearly marked. The bot always adds `#ad` and refuses to post without one.
- **X automation rules:** no duplicates, no flooding. The bot never reposts the same deal, spaces posts out, rotates categories, and varies its wording.
- **Amazon:** don't shorten or cloak Amazon links, don't scrape Amazon, and follow its rules on showing prices (see above).

## Adding another network

Create `bot/sources/yournetwork.py` with `fetch()`, which returns `Deal` objects, and `affiliate_url(deal, tracking_id)`. Register it in `bot/sources/__init__.py` and add a section in `config.yaml`. To sync its earnings, add a function to `SYNCERS` in `bot/earnings_sync.py`.

## Project layout

```
bot/
  sources/        keepa.py, ebay.py, manual.py, demo.py (one file per network)
  finder.py       fetch → filter → dedupe → approve
  autopilot.py    scoring, learning from sales, category rotation, expiry, failure cooldown
  composer.py     writes the post text (fits 280 chars, always adds #ad)
  poster.py       daily limits, budget, spacing, posting
  x_client.py     X API v2 posting (OAuth 1.0a, no extra libraries)
  earnings.py     report import + matching sales to posts
  earnings_sync.py  automatic commission sync (eBay Partner Network API)
  stats.py        numbers for the dashboard
  db.py           SQLite schema
dashboard/        Flask app, templates, styles
scripts/          Mac setup and scheduler
data/             your database and logs (not uploaded to GitHub)
```
