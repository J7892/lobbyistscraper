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
            
            print("Waiting 15 seconds for search results to generate...")
            page.wait_for_timeout(15000)
            
            # Save a debug screenshot for tracking page layout states
            page.screenshot(path="debug_screenshot.png", full_page=True)
            
            print("Harvesting elements using an element-agnostic layout scanner...")
            # This JavaScript handles BOTH traditional tables (tr) and mobile list views (li)
            raw_matrix = page.evaluate("""() => {
                let dataRecords = [];
                
                // Strategy A: Check for mobile list view items (li)
                const listItems = Array.from(document.querySelectorAll('li'));
                listItems.forEach(li => {
                    let txt = li.innerText ? li.innerText.trim() : '';
                    // Identify if the list item resembles a lobbyist registration block
                    if (txt.includes('Registration') || txt.includes('Filing') || txt.includes('Status')) {
                        // Split text lines into distinct pseudo-columns
                        let lines = txt.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                        if (lines.length > 0) {
                            dataRecords.push(lines);
                        }
                    }
                });
                
                // Strategy B: If no list cards match, fall back to traditional table rows (tr)
                if (dataRecords.length === 0) {
                    const trElements = Array.from(document.querySelectorAll('tr'));
                    trElements.forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('th, td'));
                        let cellsTxt = cells.map(c => c.innerText ? c.innerText.trim() : '');
                        if (cellsTxt.some(t => t.length > 0)) {
                            dataRecords.push(cellsTxt);
                        }
                    });
                }
                
                return dataRecords;
            }""")
            
        except Exception as e:
            msg = f"Browser automation harvesting module failed: {str(e)}"
            print(msg)
            diagnostic_holder["reason"] = msg
            browser.close()
            return None
            
        browser.close()
        
        if not raw_matrix:
            diagnostic_holder["reason"] = "Scanned the page DOM but found zero matching table rows (tr) or mobile list blocks (li)."
            return None
            
        print(f"Successfully harvested {len(raw_matrix)} data record fragments from the layout.")
        
        # Determine the header definition row dynamically
        header_row = None
        data_start_idx = 0
        
        for idx, row in enumerate(raw_matrix):
            row_upper = [str(cell).upper() for cell in row]
            if any("REGISTRATION" in cell or "FILING" in cell or "STATUS" in cell for cell in row_upper):
                header_row = [str(cell).upper() for cell in row]
                data_start_idx = idx + 1
                break
                
        # Fallback: If no dedicated header line is found, generate generic template names based on the longest row
        if not header_row:
            print("No structured header layout detected. Generating adaptive field layout...")
            max_len = max(len(r) for r in raw_matrix)
            header_row = [f"FIELD_{i}" for i in range(max_len)]
            data_start_idx = 0
            
        # Clean any missing or empty column headers
        header_row = [col if col else f"COLUMN_{i}" for i, col in enumerate(header_row)]
        
        # Format every record array to match the unified header length
        cleaned_rows = []
        for row in raw_matrix[data_start_idx:]:
            if len(row) == len(header_row):
                cleaned_rows.append(row)
            elif len(row) > len(header_row):
                cleaned_rows.append(row[:len(header_row)])
            else:
                cleaned_rows.append(row + [''] * (len(header_row) - len(row)))
                
        if not cleaned_rows:
            diagnostic_holder["reason"] = "Isolated structural field categories but zero data objects were found matching the profile."
            return None
            
        # Compile final structured dataset
        data_table = pd.DataFrame(cleaned_rows, columns=header_row)
        
        # Drop navigation or utility columns if they populate
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
        
    print(f"Successfully processed {len(current_df)} rows from the layout fields.")
    
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
