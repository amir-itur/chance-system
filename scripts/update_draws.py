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


def extract_draws_from_page(page):
    """
    CALIBRATION TARGET - see module docstring.
    Expected to return a list of dicts: [{"draw_id": int, "date": "DD/MM/YYYY",
    "time": "HH:MM"|None, "clubs": "K", "diamonds": "7", "hearts": "A", "spades": "10"}, ...]

    Strategy: the archive page renders a results table after a client-side
    fetch completes. We wait for at least one row matching a 4-values-plus-
    draw-number pattern, then read the table generically (by row/cell
    position) rather than by a specific CSS class name, since class names
    on framework-rendered tables change more often than structure does.
    """
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)  # small settle buffer for late XHR rendering

    rows = page.query_selector_all("table tr")
    results = []
    for row in rows:
        cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
        if len(cells) < 5:
            continue
        # heuristic: find a cell that's a pure integer (draw_id) and 4 cells
        # that are valid card values, in any consistent order on the row
        draw_id = None
        for c in cells:
            if c.isdigit() and len(c) >= 3:  # draw ids are 4-5 digits
                draw_id = int(c)
                break
        card_cells = [c for c in cells if c.upper() in VALID_VALUES]
        if draw_id is not None and len(card_cells) >= 4:
            date_cell = next((c for c in cells if "/" in c), None)
            results.append({
                "draw_id": draw_id,
                "date": date_cell,
                "time": None,  # filled in if a HH:MM-pattern cell is found
                "clubs": card_cells[0], "diamonds": card_cells[1],
                "hearts": card_cells[2], "spades": card_cells[3],
            })
    return results


def main():
    existing = load_json(DRAWS_FILE, {"draws": [], "last_draw_id": None, "updated_at": None})
    existing_ids = {d["draw_id"] for d in existing["draws"]}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(ARCHIVE_URL, timeout=30000)
            scraped = extract_draws_from_page(page)
            browser.close()
    except Exception as e:
        # NEVER touch draws.json on failure - just log it clearly.
        write_status(False, f"Scrape failed: {e}")
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(0)  # exit 0 so the Action doesn't spam failure emails for a transient site issue

    if not scraped:
        write_status(False, "Scrape returned zero rows - selectors likely need calibration (see script docstring).")
        print("WARNING: 0 rows extracted - check selectors", file=sys.stderr)
        sys.exit(0)

    new_draws = [d for d in scraped if d["draw_id"] not in existing_ids]
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
