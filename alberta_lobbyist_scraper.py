"""
alberta_lobbyist_scraper.py
"""
import os
import pandas as pd
from playwright.sync_api import sync_playwright

DATA_FILE = "alberta_lobbyists.csv"
BASE_URL = "https://albertalobbyistregistry.ca/"

def fetch_registry_data(diagnostic_holder):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Re-enforce a strict desktop viewport so the site doesn't load mobile menus
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        try:
            print(f"Navigating to {BASE_URL}...")
            # Use domcontentloaded to prevent the scraper from hanging on persistent government network trackers
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            
            # --- THE IRONCLAD NAVIGATION FIX ---
            print("Bypassing UI clicks. Extracting direct session URL for Search Portal...")
            search_portal_url = page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a'));
                // Find the exact link that points to the internal SRCH_REG portal
                const target = links.find(a => a.href && a.href.includes('SRCH_REG'));
                return target ? target.href : null;
            }""")
            
            if not search_portal_url:
                diagnostic_holder["reason"] = "CRITICAL: Could not find the Search Registry (SRCH_REG) link on the homepage DOM."
                browser.close()
                return None
                
            print(f"Direct URL found. Forcing browser navigation to: {search_portal_url}")
            page.goto(search_portal_url, wait_until="domcontentloaded")
            
            print("Confirming arrival on the Search portal...")
            page.wait_for_selector("input#Search, button:has-text('Search')", timeout=20000)
            page.wait_for_timeout(3000)  # 3-second buffer to allow framework scripts to bind completely
            
            print("Commanding the native APEX engine to execute the database search...")
            # Bypassing the hidden visual UI elements to execute the core backend command
            page.evaluate("""() => {
                if (typeof apex !== 'undefined' && apex.submit) {
                    apex.submit('SEARCH');
                } else {
                    const btn = document.getElementById('Search');
                    if (btn) btn.click();
                }
            }""")
            
            print("Waiting 15 seconds for the backend database engine to generate rows...")
            page.wait_for_timeout(15000)
            
        except Exception as e:
            msg = f"Browser automation navigation or interaction failed: {str(e)}"
            print(msg)
            diagnostic_holder["reason"] = msg
            page.screenshot(path="debug_screenshot.png", full_page=True)
            browser.close()
            return None
            
        # Capture screen state for artifact tracking
        page.screenshot(path="debug_screenshot.png", full_page=True)
        
        print("Harvesting the structural data matrix from the page DOM...")
        matrix = page.evaluate("""() => {
            let bestMatrix = [];
            
            // Extract standard APEX tables
            const tables = Array.from(document.querySelectorAll('table'));
            for (let table of tables) {
                const rows = Array.from(table.querySelectorAll('tr'));
                let currentMatrix = rows.map(tr => {
                    return Array.from(tr.querySelectorAll('th, td')).map(c => c.innerText ? c.innerText.replace(/\\n/g, ' ').trim() : '');
                }).filter(row => row.some(cell => cell.length > 0)); // Remove empty spacer rows
                
                if (currentMatrix.length > bestMatrix.length) {
                    bestMatrix = currentMatrix;
                }
            }
            
            // Fallback for APEX mobile card lists if tables are suppressed
            if (bestMatrix.length < 2) {
                const cards = Array.from(document.querySelectorAll('.report-data, .ui-listview li, ul.a-IRR-list li'));
                let listMatrix = [];
                for (let c of cards) {
                    let txt = c.innerText ? c.innerText.trim() : '';
                    if ((txt.includes('Filing Date') || txt.includes('Registration')) && !txt.includes('FILING AN INITIAL RETURN')) {
                        let lines = txt.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                        if (lines.length >= 3) {
                            listMatrix.push(lines);
                        }
                    }
                }
                if (listMatrix.length > 1) {
                    bestMatrix = listMatrix;
                }
            }
            
            return bestMatrix.length > 0 ? bestMatrix : null;
        }""")
        
        if not matrix or len(matrix) < 2:
            body_text = page.locator("body").inner_text()
            safe_text = body_text[:400].replace('\n', ' ') if body_text else 'No visible body text'
            diagnostic_holder["reason"] = f"Extraction failed on search page. Page text snapshot: {safe_text}"
            browser.close()
            return None
            
        browser.close()
            
        print(f"Browser successfully extracted a data matrix containing {len(matrix)} rows.")
        
        # Determine the header mapping
        header_row = [str(cell).strip().upper() for cell in matrix[0]]
        is_header = any("REGISTRATION" in col or "FILING" in col or "STATUS" in col or "NAME" in col for col in header_row)
        
        if not is_header:
            max_len = max(len(r) for r in matrix)
            header_row = [f"FIELD_{i}" for i in range(max_len)]
            data_start_idx = 0
        else:
            header_row = [col if col else f"COLUMN_{i}" for i, col in enumerate(header_row)]
            data_start_idx = 1
            
        cleaned_rows = []
        for row in matrix[data_start_idx:]:
            if not any(row):  
                continue
            if len(row) == len(header_row):
                cleaned_rows.append(row)
            elif len(row) > len(header_row):
                cleaned_rows.append(row[:len(header_row)])
            else:
                cleaned_rows.append(row + [''] * (len(header_row) - len(row)))
                
        # Build the final DataFrame
        data_table = pd.DataFrame(cleaned_rows, columns=header_row)
        
        cols_to_drop = [col for col in data_table.columns if "COLUMN_" in col or "VIEW" in col]
        if cols_to_drop:
            data_table = data_table.drop(columns=cols_to_drop)
            
        return data_table

def identify_changes(old_df, new_df):
    possible_id_cols = [col for col in new_df.columns if "NUMBER" in col or "ID" in col or "REGISTRATION" in col or "FIELD_0" in col]
    id_col = possible_id_cols[0] if possible_id_cols else new_df.columns[0]
    
    print(f"Tracking registry entries using identifier column: '{id_col}'")
    old_df[id_col] = old_df[id_col].astype(str)
    new_df[id_col] = new_df[id_col].astype(str)
    
    new_records = new_df[~new_df[id_col].isin(old_df[id_col])]
    removed_records = old_df[~old_df[id_col].isin(new_df[id_col])]
    
    common_ids = new_df[new_df[id_col].isin(old_df[id_col])][id_col]
    old_common = old_df[old_df[id_col].isin(common_ids)].set_index(id_col).sort_index()
    new_common = new_df[new_df[id_col].isin(common_ids)].set_index(id_col).sort_index()
    
    changes = []
    for idx in common_ids:
        old_row = old_common.loc[idx].fillna("")
        new_row = new_common.loc[idx].fillna("")
        
        differences = {}
        for col in new_common.columns:
            if str(old_row[col]) != str(new_row[col]):
                differences[col] = {'old': old_row[col], 'new': new_row[col]}
                
        if differences:
            changes.append({'id': idx, 'changes': differences})
            
    return new_records, removed_records, changes

def main():
    print("Starting Alberta Lobbyist Registry Scraper...")
    
    diagnostic_holder = {"reason": "Unknown processing mismatch encountered within the data pipeline."}
    current_df = fetch_registry_data(diagnostic_holder)
    
    if current_df is None or current_df.empty:
        print("Scraper execution returned zero data rows. Compiling diagnostic tracking report.")
        diagnostic_df = pd.DataFrame([{
            "SCRAPER_STATUS": "FAILED", 
            "DIAGNOSTIC_LOG": diagnostic_holder["reason"]
        }])
        diagnostic_df.to_csv(DATA_FILE, index=False)
        return
        
    print(f"Successfully processed {len(current_df)} rows from the active data grid.")
    
    is_baseline_valid = False
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        try:
            previous_df = pd.read_csv(DATA_FILE)
            if not previous_df.empty and "SCRAPER_STATUS" not in previous_df.columns:
                is_baseline_valid = True
        except Exception:
            is_baseline_valid = False

    if is_baseline_valid:
        print("Loading baseline history for change verification...")
        previous_df = pd.read_csv(DATA_FILE)
        new_recs, removed_recs, changed_recs = identify_changes(previous_df, current_df)
        
        print("\n=== POTENTIAL NEWS STORIES & ALERTS ===")
        print(f"[*] NEW REGISTRATIONS: {len(new_recs)}")
        if not new_recs.empty:
            for _, row in new_recs.iterrows():
                print(f"  -> {row.to_dict()}")
                
        print(f"\n[*] DEREGISTRATIONS/REMOVALS: {len(removed_recs)}")
        if not removed_recs.empty:
            for _, row in removed_recs.iterrows():
                print(f"  -> {row.to_dict()}")
                
        print(f"\n[*] MODIFIED REGISTRATIONS: {len(changed_recs)}")
        for change in changed_recs:
            print(f"  -> Record ID {change['id']} changed: {change['changes']}")
            
    else:
        print("\nNo tracking data found or baseline file was blank. Establishing fresh master baseline tracking file...")
        
    current_df.to_csv(DATA_FILE, index=False)
    print(f"\nMaster baseline successfully populated and updated inside '{DATA_FILE}'.")

if __name__ == "__main__":
    main()
