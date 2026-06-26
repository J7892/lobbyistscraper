"""
alberta_lobbyist_scraper.py
"""
import os
import io
import pandas as pd
from playwright.sync_api import sync_playwright

DATA_FILE = "alberta_lobbyists.csv"
BASE_URL = "https://albertalobbyistregistry.ca/"

def fetch_registry_data():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        print(f"Navigating to {BASE_URL}...")
        page.goto(BASE_URL, wait_until="networkidle")
        
        print("Clicking into the 'Search Registry' portal...")
        page.locator("text=Search Registry").first.click()
        page.wait_for_load_state("networkidle")
        
        print("Clicking the specific 'Search' button element...")
        page.locator("input#Search").click()
        
        print("Waiting 15 seconds for search results to generate...")
        page.wait_for_timeout(15000)
        
        html_content = page.content()
        browser.close()
        
        try:
            # Let Pandas extract every single table structure from the full page layout
            tables = pd.read_html(io.StringIO(html_content))
            print(f"Pandas extracted {len(tables)} potential tables from the page.")
        except Exception as e:
            print(f"Pandas failed to parse the page HTML: {e}")
            return None
            
        data_table = None
        
        # Loop through all extracted tables to pinpoint the genuine registry data grid
        for i, df in enumerate(tables):
            # Flatten or stringify headers to look for target text patterns
            col_headers = [str(col).upper() for col in df.columns]
            
            # Check if this table has the distinctive lobbyist registry columns
            is_registry_grid = any("REGISTRATION" in col or "FILING" in col for col in col_headers)
            
            if is_registry_grid and len(df) > 0:
                print(f"Found the registry data grid at table index {i}!")
                data_table = df
                
                # Standardize columns to clean uppercase strings
                data_table.columns = [str(col).strip().upper() for col in data_table.columns]
                break
                
        if data_table is None:
            print("Failed to identify the data grid using header keyword matching.")
            return None
            
        # Clean up utility or operational columns if they are present
        if 'VIEW' in data_table.columns:
            data_table = data_table.drop(columns=['VIEW'])
            
        return data_table

def identify_changes(old_df, new_df):
    # Dynamically find the primary ID/Registration column
    possible_id_cols = [col for col in new_df.columns if "NUMBER" in col or "ID" in col or "REGISTRATION" in col]
    
    if not possible_id_cols:
        id_col = new_df.columns[0]
    else:
        id_col = possible_id_cols[0]
        
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
    
    current_df = fetch_registry_data()
    if current_df is None or current_df.empty:
        print("Scraper execution returned no data. Halting file changes to protect baseline database.")
        return
        
    print(f"Successfully processed {len(current_df)} rows from the active registry window.")
    
    # Confirm if a functional baseline history exists to check against
    is_baseline_valid = False
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        try:
            previous_df = pd.read_csv(DATA_FILE)
            if not previous_df.empty and len(previous_df.columns) > 1:
                is_baseline_valid = True
        except Exception:
            is_baseline_valid = False

    if is_baseline_valid:
        print("Loading baseline snapshot history for change analysis...")
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
        print("\nNo tracking data found or baseline file was blank. Establishing a fresh tracking database...")
        
    # Write data straight to the CSV, overwriting the old blank file template
    current_df.to_csv(DATA_FILE, index=False)
    print(f"\nDatabase cleanly updated and synchronized inside '{DATA_FILE}'.")

if __name__ == "__main__":
    main()
