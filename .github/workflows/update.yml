"""
scripts/update_draws.py

Runs inside GitHub Actions on a schedule. Responsibilities:
1. Open the OFFICIAL pais.co.il Chance results archive with a real
   (headless) browser, so the JS-rendered table actually loads.
2. Extract the most recent draws.
3. Merge into docs/data/draws.json WITHOUT duplicates (keyed by draw_id).
4. Never delete or corrupt existing data on failure - on any error, leave
   the existing JSON exactly as it was and write a status file explaining
   what happened, instead of crashing silently.
5. After adding new draw(s), compare against any locked prediction
   snapshot for that draw_id (docs/data/snapshots.json) and append the
   result to docs/data/performance.json.

CALIBRATION NOTE (read this before the first real run):
The CSS selectors in `extract_draws_from_page()` are my best guess based on
the page structure already verified earlier in this project (a results
table with a CSV-download control), but I have never run this script
against the live, JS-rendered page myself - I don't have a browser tool
that executes JavaScript against external sites. The very first Actions
run is likely to need one round of selector adjustment. When it does,
check the Actions log (it prints a clear error + saves a debug
screenshot as an artifact) and send me what you see - I'll fix the
selectors precisely instead of guessing again.
"""
import json
import os
import sys
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data")
DRAWS_FILE = os.path.join(DATA_DIR, "draws.json")
SNAPSHOTS_FILE = os.path.join(DATA_DIR, "snapshots.json")
PERFORMANCE_FILE = os.path.join(DATA_DIR, "performance.json")
STATUS_FILE = os.path.join(DATA_DIR, "status.json")

ARCHIVE_URL = "https://www.pais.co.il/chance/archive.aspx"
VALID_VALUES = {"7", "8", "9", "10", "J", "Q", "K", "A"}


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic - never leaves a half-written file


def write_status(ok, message, extra=None):
    save_json(STATUS_FILE, {
        "ok": ok,
        "message": message,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "extra": extra or {},
    })


def _write_debug_log(log_lines):
    debug_dir = os.path.join(os.path.dirname(__file__), "..", "debug")
    os.makedirs(debug_dir, exist_ok=True)
    with open(os.path.join(debug_dir, "last_run_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))


def extract_draws_from_page(page, log):
    """
    Targeted extraction against the REAL page structure, confirmed from the
    debug artifact of the failed run (see chat): the archive page already
    shows the latest ~50 draws by default, NO search click needed. Each
    draw is one <li class="archive_list_item ..."> containing:
      - a[aria-vod="<draw_id>"]                      <- draw number, reliable
      - .archive_list_block.date  -> a DD/MM/YY div + a HH:MM div
      - .archive_list_block.card  -> 4x .cat_data_info, each with
            img[alt="תלתן"|"יהלום"|"לב"|"עלה"] (suit) + a sibling div (value)
    This replaces the earlier generic table/text-window heuristics, which
    both missed real data because the page uses <li>/<div>, not <table>.
    """
    import re
    log(f"page title: {page.title()!r}")

    items = page.query_selector_all("li.archive_list_item")
    log(f"found {len(items)} li.archive_list_item elements")
    if not items:
        return []

    suit_map = {"תלתן": "clubs", "יהלום": "diamonds", "לב": "hearts", "עלה": "spades"}
    date_re = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
    time_re = re.compile(r"\d{1,2}:\d{2}")

    results = []
    for item in items:
        try:
            video_link = item.query_selector("a[aria-vod]")
            draw_id = int(video_link.get_attribute("aria-vod")) if video_link else None

            date_val, time_val = None, None
            date_block = item.query_selector(".archive_list_block.date")
            if date_block:
                text = date_block.inner_text()
                m_date = date_re.search(text)
                m_time = time_re.search(text)
                date_val = m_date.group(0) if m_date else None
                time_val = m_time.group(0) if m_time else None

            cards = {}
            card_block = item.query_selector(".archive_list_block.card")
            if card_block:
                for info in card_block.query_selector_all(".cat_data_info"):
                    img = info.query_selector("img")
                    suit_key = suit_map.get(img.get_attribute("alt")) if img else None
                    value = None
                    for d in info.query_selector_all("div"):
                        t = d.inner_text().strip()
                        if t.upper() in VALID_VALUES:
                            value = t.upper()
                            break
                    if suit_key and value:
                        cards[suit_key] = value

            if draw_id and date_val and len(cards) == 4:
                results.append({"draw_id": draw_id, "date": date_val, "time": time_val, **cards})
            else:
                log(f"  skipped one li: draw_id={draw_id} date={date_val} cards_found={len(cards)}/4")
        except Exception as e:
            log(f"  error parsing one li: {e}")

    log(f"parsed {len(results)}/{len(items)} list items into draw records")
    return results


def main():
    existing = load_json(DRAWS_FILE, {"draws": [], "last_draw_id": None, "updated_at": None})
    existing_ids = {d["draw_id"] for d in existing["draws"]}

    log_lines = []
    def log(msg):
        line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
        print(line)
        log_lines.append(line)

    log(f"opening {ARCHIVE_URL}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(ARCHIVE_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            scraped = extract_draws_from_page(page, log)

            # ALWAYS save debug artifacts (not just on failure) - cheap, and the
            # first successful run is exactly when you want to sanity-check
            # that what got parsed actually matches the real page.
            debug_dir = os.path.join(os.path.dirname(__file__), "..", "debug")
            os.makedirs(debug_dir, exist_ok=True)
            page.screenshot(path=os.path.join(debug_dir, "last_run_screenshot.png"), full_page=True)
            with open(os.path.join(debug_dir, "last_run_page.html"), "w", encoding="utf-8") as f:
                f.write(page.content())
            browser.close()
    except Exception as e:
        log(f"FAILED with exception: {e}")
        write_status(False, f"Scrape failed: {e}", {"log": log_lines})
        _write_debug_log(log_lines)
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)  # non-zero: the Action shows a real red X, not a false-green success

    log(f"extraction result: {len(scraped)} draw record(s) parsed")

    if not scraped:
        write_status(False, "Scrape returned zero rows after all extraction strategies - see debug/ artifacts.", {"log": log_lines})
        _write_debug_log(log_lines)
        print("WARNING: 0 rows extracted after all strategies - see debug/last_run_page.html and debug/last_run_screenshot.png", file=sys.stderr)
        sys.exit(1)  # non-zero on purpose - section 7 of the request: never a silent false-success

    newest_scraped = max(d["draw_id"] for d in scraped)
    log(f"newest draw_id seen on page: {newest_scraped} (existing last_draw_id: {existing['last_draw_id']})")

    new_draws = [d for d in scraped if d["draw_id"] not in existing_ids]
    log(f"new (not-yet-stored) draws: {len(new_draws)}")
    if new_draws:
        existing["draws"].extend(new_draws)
        existing["draws"].sort(key=lambda d: d["draw_id"])
        existing["last_draw_id"] = existing["draws"][-1]["draw_id"]
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_json(DRAWS_FILE, existing)
        write_status(True, f"Added {len(new_draws)} new draw(s).", {"new_draw_ids": [d["draw_id"] for d in new_draws]})
        print(f"Added {len(new_draws)} new draw(s): {[d['draw_id'] for d in new_draws]}")

        # ---- compare against any locked snapshot for these draw_ids ----
        snapshots = load_json(SNAPSHOTS_FILE, {"snapshots": []})
        performance = load_json(PERFORMANCE_FILE, {"results": []})
        scored_ids = {r["draw_id"] for r in performance["results"]}
        for draw in new_draws:
            snap = next((s for s in snapshots["snapshots"] if s["target_draw_id"] == draw["draw_id"]), None)
            if snap is None or draw["draw_id"] in scored_ids:
                continue
            actual = {"clubs": draw["clubs"], "diamonds": draw["diamonds"], "hearts": draw["hearts"], "spades": draw["spades"]}
            hits = {pos: (snap["top1"][pos] == actual[pos]) for pos in actual}
            n_hit = sum(hits.values())
            top_rank = {}
            for pos in actual:
                ranking = snap.get("full_ranking", {}).get(pos, [])
                top_rank[pos] = (ranking.index(actual[pos]) + 1) if actual[pos] in ranking else None
            combo_hits = []
            for i, combo in enumerate(snap.get("combos_20", [])):
                ch = sum(1 for pos in POSITIONS if combo.get(pos) == actual[pos])
                combo_hits.append({"combo_index": i, "combo": combo, "hits": ch})
            best_combo = max(combo_hits, key=lambda c: c["hits"]) if combo_hits else None

            performance["results"].append({
                "draw_id": draw["draw_id"], "date": draw["date"],
                "snapshot_created_at": snap["created_at"],
                "predicted_top1": snap["top1"], "actual": actual,
                "hits_by_position": hits, "n_hits": n_hit, "pct": n_hit / 4 * 100,
                "rank_of_actual": top_rank, "best_combo_of_20": best_combo,
            })
        save_json(PERFORMANCE_FILE, performance)
    else:
        write_status(True, "No new draws found (up to date).")
        print("No new draws.")

    # ---- create a locked snapshot prediction for the NEXT expected draw ----
    # (runs every time, not just when new draws were found, so there's
    # always a fresh snapshot waiting for whatever draw comes next)
    create_next_snapshot(existing)
    _write_debug_log(log_lines)


VALUES = ["7", "8", "9", "10", "J", "Q", "K", "A"]
SMALL = {"7", "8", "9", "10"}
LARGE = {"J", "Q", "K", "A"}
EVEN = {"8", "10", "Q", "A"}
ODD = {"7", "9", "J", "K"}
POSITIONS = ["clubs", "diamonds", "hearts", "spades"]


def score_position(draws, pos):
    """Python port of the SAME scoring logic used in docs/index.html's
    JS engine (scoreSuitPosition) - kept deliberately identical so a
    snapshot created here matches what the dashboard would have shown
    at that moment. If you ever change the JS scoring, mirror the change
    here too (see chat: this duplication is a known tradeoff, flagged
    rather than hidden - a shared-logic refactor is a reasonable future
    step once the system is stable)."""
    seq = [d[pos] for d in draws]
    n = len(seq)
    last_seen_card = {v: -1 for v in VALUES}
    last_seen_size = {"small": -1, "large": -1}
    last_seen_parity = {"even": -1, "odd": -1}
    for i, v in enumerate(seq):
        last_seen_card[v] = i
        last_seen_size["small" if v in SMALL else "large"] = i
        last_seen_parity["even" if v in EVEN else "odd"] = i

    gap_card = {v: (n - 1 - last_seen_card[v]) if last_seen_card[v] >= 0 else n for v in VALUES}
    order = sorted(VALUES, key=lambda v: gap_card[v])
    score_card = {v: rank * 100 / 7 for rank, v in enumerate(order)}

    gap_small = (n - 1 - last_seen_size["small"]) if last_seen_size["small"] >= 0 else n
    gap_large = (n - 1 - last_seen_size["large"]) if last_seen_size["large"] >= 0 else n
    share_small = (gap_small / (gap_small + gap_large) * 100) if (gap_small + gap_large) > 0 else 50
    score_size = {v: (share_small if v in SMALL else 100 - share_small) for v in VALUES}

    gap_even = (n - 1 - last_seen_parity["even"]) if last_seen_parity["even"] >= 0 else n
    gap_odd = (n - 1 - last_seen_parity["odd"]) if last_seen_parity["odd"] >= 0 else n
    share_even = (gap_even / (gap_even + gap_odd) * 100) if (gap_even + gap_odd) > 0 else 50
    score_parity = {v: (share_even if v in EVEN else 100 - share_even) for v in VALUES}

    W = 1 / 3
    totals = {v: score_card[v] * W + score_size[v] * W + score_parity[v] * W for v in VALUES}
    ranking = sorted(VALUES, key=lambda v: -totals[v])
    return ranking, totals


def create_next_snapshot(existing):
    if not existing["draws"]:
        return
    next_draw_id = existing["last_draw_id"] + 1
    snapshots = load_json(SNAPSHOTS_FILE, {"snapshots": []})
    if any(s["target_draw_id"] == next_draw_id for s in snapshots["snapshots"]):
        return  # already have a locked snapshot waiting for this draw - never overwrite it

    draws = existing["draws"]
    rankings = {}
    totals_by_pos = {}
    for pos in POSITIONS:
        ranking, totals = score_position(draws, pos)
        rankings[pos] = ranking
        totals_by_pos[pos] = totals

    top1 = {pos: rankings[pos][0] for pos in POSITIONS}
    top3_per_pos = {pos: rankings[pos][:3] for pos in POSITIONS}

    from itertools import product
    combos = []
    for c0, c1, c2, c3 in product(*[top3_per_pos[p] for p in POSITIONS]):
        score = sum(totals_by_pos[p][v] for p, v in zip(POSITIONS, [c0, c1, c2, c3]))
        combos.append({"combo": {"clubs": c0, "diamonds": c1, "hearts": c2, "spades": c3}, "score": score})
    combos.sort(key=lambda c: -c["score"])

    snapshots["snapshots"].append({
        "target_draw_id": next_draw_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "based_on_draws_up_to": existing["last_draw_id"],
        "top1": top1,
        "full_ranking": rankings,
        "combos_20": [c["combo"] for c in combos[:20]],
        "model_version": "1.0.0-equal-weights",
        "weights": {"card": 1/3, "size": 1/3, "parity": 1/3},
    })
    save_json(SNAPSHOTS_FILE, snapshots)
    print(f"Locked new snapshot for draw #{next_draw_id}")


if __name__ == "__main__":
    main()
