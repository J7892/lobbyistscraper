"""
alberta_lobbyist_scraper.py

Scrapes the Alberta Lobbyist Registry for all active registrations and tracks
new registrations, deregistrations, and field-level changes between runs.
"""

import os
import json
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DATA_FILE = "alberta_lobbyists.csv"
HTML_DUMP_FILE = "debug_page.html"
SCREENSHOT_FILE = "debug_screenshot.png"
BASE_URL = "https://albertalobbyistregistry.ca/"


# ---------------------------------------------------------------------------
# Page interaction helpers
# ---------------------------------------------------------------------------

def _save_diagnostics(page):
    """Always save a screenshot and the full rendered HTML for debugging."""
    try:
        page.screenshot(path=SCREENSHOT_FILE, full_page=True)
        with open(HTML_DUMP_FILE, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"  [debug] Saved screenshot → {SCREENSHOT_FILE}")
        print(f"  [debug] Saved HTML dump  → {HTML_DUMP_FILE}")
    except Exception as e:
        print(f"  [debug] Could not save diagnostics: {e}")


def _extract_table_data(page):
    """
    Try multiple strategies to pull tabular data out of the rendered DOM.

    The Alberta registry uses jQuery Mobile, which renders search results as
    <ul data-role="listview"> / <li> elements rather than a <table>.  The JS
    below walks the DOM and tries several structures in order.

    Returns a list-of-dicts (one dict per row) or None on failure.
    """
    return page.evaluate(r"""() => {
        // ── Helper ───────────────────────────────────────────────────────
        function textOf(el) {
            return (el && el.innerText) ? el.innerText.trim() : '';
        }

        // ── Strategy 1: Standard <table> with at least 2 rows ────────────
        for (const table of document.querySelectorAll('table')) {
            const rows = Array.from(table.querySelectorAll('tr'));
            if (rows.length < 2) continue;

            const headers = Array.from(rows[0].querySelectorAll('th, td'))
                                 .map(c => textOf(c).toUpperCase() || 'COLUMN');
            const data = [];
            for (let i = 1; i < rows.length; i++) {
                const cells = Array.from(rows[i].querySelectorAll('td, th'));
                if (!cells.some(c => textOf(c))) continue;   // skip blank rows
                const obj = {};
                cells.forEach((c, idx) => {
                    obj[headers[idx] || `COL_${idx}`] = textOf(c);
                });
                data.push(obj);
            }
            if (data.length > 0) return { source: 'table', rows: data };
        }

        // ── Strategy 2: jQuery Mobile listview (<ul data-role="listview">) ─
        //   Each <li> typically contains labelled <span> pairs or <h3>/<p> tags.
        const listviews = document.querySelectorAll('[data-role="listview"] li, ul.ui-listview li');
        if (listviews.length > 0) {
            const data = [];
            for (const li of listviews) {
                const obj = {};
                // Grab every visible line as "Label: Value" pairs
                const text = textOf(li);
                if (!text) continue;

                // Try to parse "Key: Value\nKey: Value" patterns
                const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
                for (const line of lines) {
                    const colonIdx = line.indexOf(':');
                    if (colonIdx > 0 && colonIdx < line.length - 1) {
                        const key = line.slice(0, colonIdx).trim().toUpperCase().replace(/\s+/g, '_');
                        const val = line.slice(colonIdx + 1).trim();
                        obj[key] = val;
                    } else {
                        // No colon — store as RAW_TEXT_N
                        const n = Object.keys(obj).filter(k => k.startsWith('RAW_TEXT')).length;
                        obj[`RAW_TEXT_${n}`] = line;
                    }
                }
                if (Object.keys(obj).length > 0) data.push(obj);
            }
            if (data.length > 0) return { source: 'listview', rows: data };
        }

        // ── Strategy 3: Any <div> or <li> whose text looks like a registry row ─
        const candidates = document.querySelectorAll('li, div');
        const data = [];
        for (const el of candidates) {
            // Only look at leaf-ish elements (no deeply nested children that would
            // cause double-counting)
            if (el.querySelectorAll('li, div').length > 3) continue;
            const text = textOf(el);
            // Heuristic: registry rows mention "Registration" or a lobbyist name
            if (!text || text.length < 10) continue;
            if (!/registration|lobbyist|filing|active|inactive/i.test(text)) continue;

            const obj = {};
            const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
            lines.forEach((line, i) => {
                const colonIdx = line.indexOf(':');
                if (colonIdx > 0) {
                    const key = line.slice(0, colonIdx).trim().toUpperCase().replace(/\s+/g, '_');
                    obj[key] = line.slice(colonIdx + 1).trim();
                } else {
                    obj[`FIELD_${i}`] = line;
                }
            });
            data.push(obj);
        }
        if (data.length > 0) return { source: 'div_heuristic', rows: data };

        // ── Strategy 4: Dump everything visible on the page ──────────────
        //   Last resort — grab all text so we at least know what rendered.
        const body = document.body ? document.body.innerText : '';
        return { source: 'body_text', rows: [{ RAW_BODY: body }] };
    }""")


# ---------------------------------------------------------------------------
# Main fetch function
# ---------------------------------------------------------------------------

def fetch_registry_data(diagnostic_holder):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        try:
            # ── 1. Load homepage ─────────────────────────────────────────
            print(f"Navigating to {BASE_URL} ...")
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_load_state("networkidle", timeout=20_000)

            # ── 2. Click "Search Registry" ───────────────────────────────
            print("Clicking 'Search Registry' link ...")
            # Try several selectors in order of specificity
            for selector in [
                "a:has-text('Search Registry')",
                "text=Search Registry",
                "a[href*='search']",
            ]:
                try:
                    page.locator(selector).first.click(timeout=8_000)
                    break
                except Exception:
                    continue

            page.wait_for_load_state("networkidle", timeout=20_000)

            # ── 3. Click the Search / Submit button ──────────────────────
            print("Submitting search form (blank = return all records) ...")
            # jQuery Mobile wraps <button>/<input> inside <div class="ui-btn">
            # The actual clickable layer is the outer div, not the inner span.
            submitted = False
            for selector in [
                "input[type='submit'][value*='Search']",
                "button:has-text('Search')",
                "div.ui-btn:has-text('Search')",   # jQM outer wrapper
                "a[data-role='button']:has-text('Search')",
                "span.ui-btn-text:has-text('Search')",  # last resort — inner span
            ]:
                try:
                    btn = page.locator(selector).first
                    btn.wait_for(state="visible", timeout=8_000)
                    btn.click()
                    submitted = True
                    print(f"  Clicked search button via selector: {selector}")
                    break
                except Exception:
                    continue

            if not submitted:
                raise RuntimeError(
                    "Could not locate or click the Search button. "
                    "Check debug_screenshot.png to see what rendered."
                )

            # ── 4. Wait for results ──────────────────────────────────────
            # Prefer waiting for a known results container; fall back to a
            # generous timeout if we can't identify one.
            print("Waiting for search results to appear ...")
            result_appeared = False
            for results_selector in [
                "[data-role='listview'] li",
                "table tr:nth-child(2)",   # at least 2 rows = header + 1 result
                ".results",
                "#results",
                "[id*='result'] tr",
            ]:
                try:
                    page.wait_for_selector(
                        results_selector, state="visible", timeout=20_000
                    )
                    print(f"  Results detected via: {results_selector}")
                    result_appeared = True
                    break
                except PlaywrightTimeoutError:
                    continue

            if not result_appeared:
                # Hard fallback: just wait and hope
                print("  Could not detect a results container — waiting 12 s ...")
                page.wait_for_timeout(12_000)

        except Exception as exc:
            msg = f"Navigation/interaction failed: {exc}"
            print(f"ERROR: {msg}")
            diagnostic_holder["reason"] = msg
            _save_diagnostics(page)
            browser.close()
            return None

        # ── 5. Save diagnostics (always, even on success) ─────────────────
        _save_diagnostics(page)

        # ── 6. Extract data ───────────────────────────────────────────────
        print("Extracting data from DOM ...")
        result = _extract_table_data(page)
        browser.close()

        if not result or not result.get("rows"):
            diagnostic_holder["reason"] = (
                "DOM extraction returned no rows. "
                "Inspect debug_screenshot.png and debug_page.html."
            )
            return None

        source = result["source"]
        rows   = result["rows"]
        print(f"  Extraction source: '{source}' — {len(rows)} row(s) found.")

        if source == "body_text":
            diagnostic_holder["reason"] = (
                "Fell back to raw body text — no structured data found. "
                "Inspect debug_page.html to understand the rendered DOM."
            )
            return None

        # ── 7. Normalise into a DataFrame ─────────────────────────────────
        df = pd.DataFrame(rows)

        # Drop columns that are entirely empty
        df = df.dropna(axis=1, how="all")
        df = df.loc[:, (df != "").any(axis=0)]

        # Drop obvious junk columns
        junk_patterns = ["COLUMN_", "VIEW", "SELECT", "ACTION"]
        drop_cols = [c for c in df.columns if any(p in c for p in junk_patterns)]
        if drop_cols:
            df = df.drop(columns=drop_cols)

        print(f"  Final DataFrame: {len(df)} rows × {len(df.columns)} columns.")
        print(f"  Columns: {list(df.columns)}")
        return df


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

def identify_changes(old_df: pd.DataFrame, new_df: pd.DataFrame):
    # Pick the best identifier column
    id_candidates = [
        c for c in new_df.columns
        if any(kw in c for kw in ("NUMBER", "ID", "REGISTRATION", "REG_"))
    ]
    id_col = id_candidates[0] if id_candidates else new_df.columns[0]
    print(f"Using '{id_col}' as the unique identifier for change tracking.")

    old_df[id_col] = old_df[id_col].astype(str).str.strip()
    new_df[id_col] = new_df[id_col].astype(str).str.strip()

    old_ids = set(old_df[id_col])
    new_ids = set(new_df[id_col])

    new_recs     = new_df[new_df[id_col].isin(new_ids - old_ids)]
    removed_recs = old_df[old_df[id_col].isin(old_ids - new_ids)]

    # Field-level diff for records present in both snapshots
    common_ids = new_ids & old_ids
    old_idx = old_df[old_df[id_col].isin(common_ids)].set_index(id_col)
    new_idx = new_df[new_df[id_col].isin(common_ids)].set_index(id_col)

    shared_cols = [c for c in new_idx.columns if c in old_idx.columns and c != id_col]
    changes = []
    for rec_id in common_ids:
        try:
            old_row = old_idx.loc[rec_id]
            new_row = new_idx.loc[rec_id]
        except KeyError:
            continue
        diffs = {
            col: {"old": str(old_row[col]), "new": str(new_row[col])}
            for col in shared_cols
            if str(old_row.get(col, "")).strip() != str(new_row.get(col, "")).strip()
        }
        if diffs:
            changes.append({"id": rec_id, "changes": diffs})

    return new_recs, removed_recs, changes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Alberta Lobbyist Registry Scraper")
    print("=" * 60)

    diagnostic_holder = {"reason": "Unknown error."}
    current_df = fetch_registry_data(diagnostic_holder)

    if current_df is None or current_df.empty:
        print("\nScraper returned no data. Writing diagnostic CSV.")
        pd.DataFrame([{
            "SCRAPER_STATUS": "FAILED",
            "DIAGNOSTIC_LOG": diagnostic_holder["reason"],
        }]).to_csv(DATA_FILE, index=False)
        return

    print(f"\nSuccessfully scraped {len(current_df)} records.")

    # Check for a valid prior baseline
    baseline_valid = False
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        try:
            prev_df = pd.read_csv(DATA_FILE)
            if not prev_df.empty and "SCRAPER_STATUS" not in prev_df.columns:
                baseline_valid = True
        except Exception:
            pass

    if baseline_valid:
        prev_df = pd.read_csv(DATA_FILE)
        print("\nComparing against previous snapshot ...")
        new_recs, removed_recs, changed_recs = identify_changes(prev_df, current_df)

        print("\n=== CHANGE REPORT ===")
        print(f"NEW REGISTRATIONS   : {len(new_recs)}")
        for _, row in new_recs.iterrows():
            print(f"  + {row.to_dict()}")

        print(f"\nDEREGISTRATIONS     : {len(removed_recs)}")
        for _, row in removed_recs.iterrows():
            print(f"  - {row.to_dict()}")

        print(f"\nMODIFIED RECORDS    : {len(changed_recs)}")
        for item in changed_recs:
            print(f"  ~ ID {item['id']}: {json.dumps(item['changes'], indent=4)}")

        if not new_recs.empty or not removed_recs.empty or changed_recs:
            print("\n*** Changes detected — review the output above. ***")
        else:
            print("\nNo changes since last run.")
    else:
        print("\nNo valid baseline found — establishing initial snapshot.")

    current_df.to_csv(DATA_FILE, index=False)
    print(f"\nSnapshot saved to '{DATA_FILE}'.")


if __name__ == "__main__":
    main()
