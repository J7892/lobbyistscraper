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
            page.wait_for_load_state("networkidle")
            
            # --- CRITICAL FIX: Target the actual visible button text layer ---
            print("Locating the visible 'Search' action trigger...")
            visible_search_btn = page.locator("span.ui-btn-text").filter(has_text="Search").first
            visible_search_btn.wait_for(state="visible", timeout=25000)
            
            print("Clicking the visible 'Search' button...")
            visible_search_btn.click()
            
            # Wait for the actual data table headers to load on screen
            print("Waiting for data table rows to render...")
            page.wait_for_selector("text=Registration Number", timeout=30000)
            print("Registry grid successfully initialized!")
            
            # Small 3-second safety window to ensure AJAX data frames finish populating
            page.wait_for_timeout(3000)
            
        except Exception as e:
            msg = f"Browser execution failed to execute query: {str(e)}"
            print(msg)
            diagnostic_holder["reason"] = msg
            page.screenshot(path="debug_screenshot.png", full_page=True)
            browser.close()
            return None
            
        page.screenshot(path="debug_screenshot.png", full_page=True)
        html_content = page.content()
        browser.close()
        
        try:
            # Re-introduce pandas read_html to cleanly parse the validated grid markup
            tables = pd.read_html(io.StringIO(html_content))
            print(f"Pandas parsed {len(tables)} structural elements from layout content.")
        except Exception as e:
            diagnostic_holder["reason"] = f"Pandas failed to structurally parse layout: {str(e)}"
            return None
            
        data_table = None
        for idx, df in enumerate(tables):
            if df.empty:
                continue
            cols_clean = [str(c).upper() for c in df.columns]
            if any("REGISTRATION" in col or "FILING" in col for col in cols_clean):
                print(f"Isolated genuine data matrix at index {idx}.")
                data_table = df
                data_table.columns = [str(c).strip().upper() for c in data_table.columns]
                break
                
        if data_table is None:
            diagnostic_holder["reason"] = "Query submitted successfully, but column signature matching failed."
            return None
            
        if 'VIEW' in data_table.columns:
            data_table = data_table.drop(columns=['VIEW'])
            
        return data_table

def identify_changes(old_df, new_df):
    possible_id_cols = [col for col in new_df.columns if "NUMBER" in col or "ID" in col or "REGISTRATION" in col]
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
    
    diagnostic_holder = {"reason": "Unknown parsing mismatch encountered within the data pipeline."}
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
