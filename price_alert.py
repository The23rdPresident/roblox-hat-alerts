#!/usr/bin/env python3
"""
Roblox limited price alerts -> Discord.

This file checks prices once. GitHub Actions schedules it; the companion
roblox_price_alert.py runs it continuously on a background worker.
Credentials come from environment variables. Python standard library only.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# ------------------------------ settings ------------------------------
WATCHLIST = [
    # (asset ID from the catalog link, alert when the cheapest listing is under this many Robux)
    (878895806, 80_000),    # Gold Emperor of the Night
    (878899787, 120_000),   # Silver Emperor of the Night
    (169444294, 80_000),    # Stickmasterluke's Peanut Butter Sparkle Time
]

# If the same cheap listing is still up, send a reminder after this many seconds.
REMIND_AFTER = 30 * 60

# Ping @everyone in the channel when a hat is listed under its target.
PING_EVERYONE = os.environ.get("PING_EVERYONE", "true").lower() in {"1", "true", "yes", "on"}

# Warn you on Discord if Roblox can't be reached for this long.
WARN_AFTER_FAILING = 60 * 60
# ----------------------------------------------------------------------

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "").strip()
MANUAL_RUN = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
STATE_FILE = os.environ.get("PRICE_ALERT_STATE_FILE", "state.json")
TEST_ALERT = os.environ.get("TEST_ALERT", "false").lower() in {"1", "true", "yes", "on"}

ROBLOX_HEADERS = {"User-Agent": "Mozilla/5.0 (price-alert script)", "Accept": "application/json"}
# Discord rejects Python's default user agent, so set our own.
DISCORD_HEADERS = {"User-Agent": "DiscordBot (price-alert, 1.0)", "Content-Type": "application/json"}
EMBED_COLOR = 0x2ECC71
WARN_COLOR = 0xE67E22


def log(msg):
    print(msg, flush=True)


def fmt(price):
    return "no copies listed" if price is None else f"{price:,} Robux"


def catalog_url(asset_id):
    return f"https://www.roblox.com/catalog/{asset_id}"


def get_json(url):
    req = urllib.request.Request(url, headers=ROBLOX_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def get_listing(asset_id):
    """Return (name, lowest price, listing id). Price is None if no copies are listed."""
    data = get_json(f"https://economy.roblox.com/v2/assets/{asset_id}/details")
    details = data.get("CollectiblesItemDetails")
    if not isinstance(details, dict) or "CollectibleLowestResalePrice" not in details:
        raise ValueError("Roblox did not return the expected resale-price fields")
    price = details.get("CollectibleLowestResalePrice")
    if price is not None and (type(price) is not int or price < 0):
        raise ValueError("Roblox returned an invalid resale price")
    return (
        data.get("Name") or f"Item {asset_id}",
        price,
        details.get("CollectibleLowestAvailableResaleItemInstanceId"),
    )


def get_thumbnail(asset_id):
    try:
        data = get_json(
            "https://thumbnails.roblox.com/v1/assets"
            f"?assetIds={asset_id}&returnPolicy=PlaceHolder&size=420x420&format=Png&isCircular=false"
        )
        return (data.get("data") or [{}])[0].get("imageUrl")
    except Exception:
        return None


def send_discord(content="", embeds=None, ping=False):
    mentions = {"parse": []}
    if ping:
        tags = []
        if PING_EVERYONE:
            tags.append("@everyone")
            mentions["parse"] = ["everyone"]
        if DISCORD_USER_ID:
            tags.append(f"<@{DISCORD_USER_ID}>")
            mentions["users"] = [DISCORD_USER_ID]
        content = f"{' '.join(tags)} {content}".strip()
    payload = {"content": content, "allowed_mentions": mentions}
    if embeds:
        payload["embeds"] = embeds
    body = json.dumps(payload).encode()

    for _ in range(3):
        req = urllib.request.Request(WEBHOOK_URL, data=body, headers=DISCORD_HEADERS, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Discord rate limit: wait as long as it asks, then retry
                try:
                    wait = float(json.load(e).get("retry_after", 2))
                except Exception:
                    wait = 2
                time.sleep(wait + 0.5)
                continue
            log(f"Discord rejected the message (HTTP {e.code}). Check the DISCORD_WEBHOOK_URL environment setting.")
            return False
        except Exception as e:
            log(f"Couldn't reach Discord ({type(e).__name__}); retrying.")
            time.sleep(3)
    return False


def send_alert(asset_id, name, price, target, reminder):
    embed = {
        "title": f"Lowest price: {price:,} Robux",
        "url": catalog_url(asset_id),
        "description": f"**{name}** is listed under your **{target:,} Robux** target.",
        "color": EMBED_COLOR,
        "fields": [
            {"name": "Your target", "value": f"Under {target:,}", "inline": True},
            {"name": "Under target by", "value": f"{target - price:,}", "inline": True},
        ],
        "footer": {"text": "Still listed" if reminder else "New low listing"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    thumb = get_thumbnail(asset_id)
    if thumb:
        embed["thumbnail"] = {"url": thumb}
    return send_discord(content=catalog_url(asset_id), embeds=[embed], ping=True)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as file:
            state = json.load(file)
        if not isinstance(state, dict) or not isinstance(state.get("items"), dict):
            raise ValueError("invalid state format")
        state.setdefault("fail_since", None)
        state.setdefault("fail_warned", False)
        return state
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, ValueError):
        log("Saved alert state is invalid; rebuilding it. Existing cheap listings may alert again.")
        return None


def save_state(state):
    path = Path(STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)
        file.write("\n")
    os.replace(temporary, path)


def validate_settings():
    parts = urlsplit(WEBHOOK_URL)
    if (parts.scheme != "https" or parts.netloc != "discord.com"
            or not re.fullmatch(r"/api/(?:v[0-9]+/)?webhooks/[0-9]+/[A-Za-z0-9_-]+", parts.path)
            or parts.query or parts.fragment):
        log("DISCORD_WEBHOOK_URL is missing or invalid. Set the full Discord webhook URL in your host's secrets/environment settings.")
        raise SystemExit(1)
    if DISCORD_USER_ID and not DISCORD_USER_ID.isdigit():
        log("DISCORD_USER_ID must contain only your numeric Discord user ID.")
        raise SystemExit(1)


def send_test_alert():
    asset_id, target = WATCHLIST[0]
    price = target - 1
    embed = {
        "title": "🧪 Test price alert",
        "url": catalog_url(asset_id),
        "description": "**Simulated notification only.** This does not mean a hat is currently listed at this price.",
        "color": EMBED_COLOR,
        "fields": [
            {"name": "Example price", "value": fmt(price), "inline": True},
            {"name": "Target", "value": f"Under {target:,} Robux", "inline": True},
        ],
        "footer": {"text": "Webhook test • Alert state is unchanged"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return send_discord(content=catalog_url(asset_id), embeds=[embed], ping=True)


def main():
    validate_settings()
    if TEST_ALERT and not send_test_alert():
        raise SystemExit(1)

    old_state = load_state()
    first_run = old_state is None
    state = json.loads(json.dumps(old_state or {"items": {}, "fail_since": None, "fail_warned": False}))
    now = time.time()
    # A daily health record also produces legitimate repository activity on quiet days.
    state["last_attempt_day"] = datetime.fromtimestamp(now, timezone.utc).date().isoformat()

    status_fields = []
    failures = 0
    rate_limited = False

    for asset_id, target in WATCHLIST:
        key = str(asset_id)
        try:
            name, price, listing = get_listing(asset_id)
        except Exception as e:
            failures += 1
            rate_limited = rate_limited or (isinstance(e, urllib.error.HTTPError) and e.code == 429)
            log(f"Price check for {asset_id} failed: {e}")
            continue
        finally:
            time.sleep(1)  # space out requests to Roblox

        log(f"{name}: {fmt(price)} (alert under {target:,})")
        status_fields.append({
            "name": name,
            "value": f"Now: {fmt(price)}\nAlert under: {target:,} Robux\n{catalog_url(asset_id)}",
        })

        item = state["items"].setdefault(key, {"listing": None, "price": None, "at": 0})

        if price is None or price >= target:
            item.update(listing=None, price=None, at=0)  # reset so the next dip alerts again
            continue

        is_new = listing != item["listing"]
        is_cheaper = item["price"] is None or price < item["price"]
        reminder_due = now - item["at"] >= REMIND_AFTER
        if not (is_new or is_cheaper or reminder_due):
            log("  Already pinged about this listing.")
            continue

        if send_alert(asset_id, name, price, target, reminder=not (is_new or is_cheaper)):
            log(f"  Alert sent at {price:,} Robux.")
            item.update(listing=listing, price=price, at=int(now))

    # Warn once when all monitored Roblox price endpoints have failed for an hour.
    if status_fields:
        state["last_success_day"] = state["last_attempt_day"]

    if failures == len(WATCHLIST):
        if state["fail_since"] is None:
            state["fail_since"] = int(now)
        elif not state["fail_warned"] and now - state["fail_since"] >= WARN_AFTER_FAILING:
            if send_discord(embeds=[{
                "title": "⚠️ Price watcher can't reach Roblox",
                "description": "All monitored price checks have been failing for over an hour. "
                               "Alerts are paused until Roblox answers again; you'll get a note when it does.",
                "color": WARN_COLOR,
            }]):
                state["fail_warned"] = True
    elif failures == 0:
        if state["fail_warned"]:
            send_discord(embeds=[{"title": "✅ Price watcher is checking prices again", "color": EMBED_COLOR}])
        state["fail_since"] = None
        state["fail_warned"] = False

    # First run or a manual run from the Actions tab: post where each price is now.
    if (first_run or MANUAL_RUN) and status_fields:
        title = "👀 Price watcher started" if first_run else "📋 Current prices"
        send_discord(embeds=[{
            "title": title,
            "description": "You'll get pinged when any of these is listed under its target.",
            "color": EMBED_COLOR,
            "fields": status_fields,
        }])

    if state != old_state:
        save_state(state)

    return 120 if rate_limited else 0


if __name__ == "__main__":
    main()
