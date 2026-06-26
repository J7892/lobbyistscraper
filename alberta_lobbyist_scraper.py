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
            
            print("Clicking the specific 'Search' button element...")
            page.locator("input#Search").click()
            
            # --- FIX: Wait for the visual column text to appear instead of a class name ---
            print("Waiting for visual registry column headers to render...")
            page.wait_for_selector("text=Registration Number", timeout=45000)
            print("Data grid text successfully detected on screen!")
            
        except Exception as e:
            msg = f"Browser automation navigation or click failed: {str(e)}"
            print(msg)
            diagnostic_holder["reason"] = msg
            page.screenshot(path="debug_screenshot.png", full_page=True)
            browser.close()
            return None
            
        # Take a success screenshot for artifact tracking
        page.screenshot(path="debug_screenshot.png", full_page=True)
        
        print("Extracting table rows via text matching...")
        matrix = page.evaluate("""() => {
            const tables = Array.from(document.querySelectorAll('table'));
            // Find the table container that holds the visible registration data
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
            diagnostic_holder["reason"] = "DOM extraction completed but the resulting text matrix was empty or structurally invalid."
            return None
            
        print(f"Browser successfully parsed a text matrix containing {len(matrix)} rows.")
        
        # Standardize the headers based on the first extracted row containing valid column markers
        header_row = [str(cell).strip().upper() for cell in matrix[0]]
        header_row = [col if col else f"COLUMN_{i}" for i, col in enumerate(header_row)]
        
        cleaned_rows = []
        for row in matrix[1:]:
            if not any(row):  # Skip completely empty lines
                continue
            if len(row) == len(header_row):
                cleaned_rows.append(row)
            elif len(row) > len(header_row):
                cleaned_rows.append(row[:len(header_row)])
            else:
                cleaned_rows.append(row + [''] * (len(header_row) - len(row)))
                
        data_table = pd.DataFrame(cleaned_rows, columns=header_row)
        
        # Drop common non-data columns if they populate
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
        
    print(f"Tracking registry records using unique column key: '{id_col}'")
    
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
    
    # Dictionary to pass error messages out of the browser routine if it fails
    diagnostic_holder = {"reason": "Unknown parsing exception encountered inside extraction loops."}
    current_df = fetch_registry_data(diagnostic_holder)
    
    # If extraction fails, write the exact error message caught into the CSV file
    if current_df is None or current_df.empty:
        print("Scraper execution returned zero data records. Generating specific diagnostic tracking file.")
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
        print("\nNo functional tracking baseline detected. Establishing fresh master baseline tracking file...")
        
    current_df.to_csv(DATA_FILE, index=False)
    print(f"\nMaster baseline successfully populated and updated inside '{DATA_FILE}'.")

if __name__ == "__main__":
    main()
