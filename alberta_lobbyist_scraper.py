"""
alberta_lobbyist_scraper.py
"""
import os
import io
import pandas as pd
from playwright.sync_api import sync_playwright

DATA_FILE = "alberta_lobbyists.csv"
BASE_URL = "https://albertalobbyistregistry.ca/"

def fetch_registry_data(diagnostic_holder):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        try:
            print(f"Navigating to {BASE_URL}...")
            page.goto(BASE_URL, wait_until="networkidle")
            
            print("Clicking into the 'Search Registry' portal...")
            page.locator("text=Search Registry").first.click()
            
            # --- CRITICAL FIX: Stop and anchor here until the search page element is visible ---
            print("Waiting for the Search Portal page context to load...")
            page.wait_for_selector("input#Search", timeout=25000)
            print("Search Portal loaded successfully. Executing search query...")
            
            # Click the search button directly now that we know we are on the right page
            page.locator("input#Search").click()
            
            print("Waiting 15 seconds for the database grid to completely render...")
            page.wait_for_timeout(15000)
            
        except Exception as e:
            msg = f"Browser automation navigation or page sync failed: {str(e)}"
            print(msg)
            diagnostic_holder["reason"] = msg
            page.screenshot(path="debug_screenshot.png", full_page=True)
            browser.close()
            return None
            
        # Capture an updated screenshot for artifact tracking
        page.screenshot(path="debug_screenshot.png", full_page=True)
        html_content = page.content()
        browser.close()
        
        try:
            # Let Pandas extract all structural tables on the page
            tables = pd.read_html(io.StringIO(html_content))
            print(f"Pandas parsed {len(tables)} structural tables from the target layout.")
        except Exception as e:
            diagnostic_holder["reason"] = f"Pandas structural parsing exception: {str(e)}"
            return None
            
        data_table = None
        table_diagnostics = []
        
        # Deep inspection of all discovered tables to find the genuine grid
        for idx, df in enumerate(tables):
            if df.empty:
                continue
                
            # Flatten columns and top data row to look for target keywords
            cols_clean = [str(c).upper() for c in df.columns]
            first_row_clean = [str(x).upper() for x in df.iloc[0].values] if len(df) > 0 else []
            combined_fingerprint = " ".join(cols_clean + first_row_clean)
            
            table_diagnostics.append(f"Table {idx} shape={df.shape} text='{combined_fingerprint[:60]}...'")
            
            # Look for fuzzy matching signature columns
            if any("REGISTRATION" in token or "FILING" in token for token in cols_clean + first_row_clean):
                print(f"Match found! Target registry grid isolated at table index {idx}.")
                data_table = df
                break
                
        if data_table is None:
            diagnostic_holder["reason"] = f"Failed to match registry keywords against table signatures. Discovered: {'; '.join(table_diagnostics)}"
            return None
            
        # Clean up columns format
        data_table.columns = [str(col).strip().upper() for col in data_table.columns]
        if 'VIEW' in data_table.columns:
            data_table = data_table.drop(columns=['VIEW'])
            
        return data_table

def identify_changes(old_df, new_df):
    possible_id_cols = [col for col in new_df.columns if "NUMBER" in col or "ID" in col or "REGISTRATION" in col]
    id_col = possible_id_cols[0] if possible_id_cols else new_df.columns[0]
    
    print(f"Tracking registry records using identifier key: '{id_col}'")
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
        
    print(f"Successfully processed {len(current_df)} rows from the data grid.")
    
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
