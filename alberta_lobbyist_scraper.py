"""
alberta_lobbyist_scraper.py
"""
import os
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
        
        print("Extracting data matrix directly from the browser DOM...")
        # Execute JavaScript directly in the browser context to rip clean text values
        matrix = page.evaluate("""() => {
            const tables = Array.from(document.querySelectorAll('table'));
            // Find the core data table containing the key registration text
            const targetTable = tables.find(t => t.innerText && t.innerText.includes('Registration Number'));
            if (!targetTable) return null;
            
            const rows = Array.from(targetTable.querySelectorAll('tr'));
            return rows.map(row => {
                const cells = Array.from(row.querySelectorAll('th, td'));
                return cells.map(c => c.innerText ? c.innerText.trim() : '');
            });
        }""")
        
        browser.close()
        
        if not matrix or len(matrix) < 2:
            print("Failed to isolate the registry grid via browser DOM evaluation.")
            return None
            
        print(f"Browser successfully extracted a text matrix with {len(matrix)} raw elements.")
        
        # Dynamically find the header row index
        header_row = None
        data_start_idx = 1
        for idx, row in enumerate(matrix):
            if any("REGISTRATION" in str(cell).upper() for cell in row):
                header_row = [str(cell).strip().upper() for cell in row]
                data_start_idx = idx + 1
                break
                
        if not header_row:
            print("Could not find a row containing the expected column headers.")
            return None
            
        # Clean up empty header values (like the unlabeled first column link)
        header_row = [col if col else f"COLUMN_{i}" for i, col in enumerate(header_row)]
        
        # Conform all data row lengths to header lengths to avoid Pandas construction issues
        cleaned_rows = []
        for row in matrix[data_start_idx:]:
            if not any(row):  # Skip completely blank lines
                continue
            if len(row) == len(header_row):
                cleaned_rows.append(row)
            elif len(row) > len(header_row):
                cleaned_rows.append(row[:len(header_row)])
            else:
                cleaned_rows.append(row + [''] * (len(header_row) - len(row)))
        
        if not cleaned_rows:
            print("No data rows remained after structural sanitization.")
            return None
            
        # Create our clean DataFrame
        data_table = pd.DataFrame(cleaned_rows, columns=header_row)
        
        # Drop completely blank column templates or navigation columns
        cols_to_drop = [col for col in data_table.columns if "COLUMN_" in col or "VIEW" in col]
        if cols_to_drop:
            data_table = data_table.drop(columns=cols_to_drop)
            
        return data_table

def identify_changes(old_df, new_df):
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
        
    current_df.to_csv(DATA_FILE, index=False)
    print(f"\nDatabase cleanly updated and synchronized inside '{DATA_FILE}'.")

if __name__ == "__main__":
    main()
