"""
alberta_lobbyist_scraper.py
"""
import os
import io
import pandas as pd
from bs4 import BeautifulSoup
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
        
        # --- FIX: Use BeautifulSoup to isolate the exact data table ---
        soup = BeautifulSoup(html_content, 'html.parser')
        target_table = None
        
        for table in soup.find_all('table'):
            table_text = table.text
            if "Filing Date" in table_text and "Registration Number" in table_text:
                target_table = table
                break
                
        if target_table is None:
            print("Failed to isolate the data table from the page structure.")
            return None
            
        try:
            # Pass only the targeted table HTML snippet to Pandas
            tables = pd.read_html(io.StringIO(str(target_table)))
            data_table = tables[0]
        except ValueError:
            print("Pandas failed to parse the isolated table snippet.")
            return None
        
        # Clean up column names for consistency
        data_table.columns = [str(col).strip().upper() for col in data_table.columns]
        
        # Drop completely empty columns or utility columns like 'VIEW' if they exist
        if 'VIEW' in data_table.columns:
            data_table = data_table.drop(columns=['VIEW'])
            
        return data_table

def identify_changes(old_df, new_df):
    possible_id_cols = [col for col in new_df.columns if "NUMBER" in col or "ID" in col]
    
    if not possible_id_cols:
        print("Warning: Could not find a definitive ID column. Using row index as a fallback.")
        id_col = new_df.columns[0]
    else:
        id_col = possible_id_cols[0]
        
    print(f"Tracking entities using the '{id_col}' column.")
    
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
        print("Failed to extract data. Keeping existing file baseline.")
        return
        
    print(f"Extracted {len(current_df)} current registry rows.")
    
    # Check if a valid baseline exists (file exists and is larger than 0 bytes)
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        print("Loading previous baseline for comparison...")
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
        print("\nNo previous data found. Establishing a new baseline...")
        
    current_df.to_csv(DATA_FILE, index=False)
    print(f"\nState saved to {DATA_FILE}.")

if __name__ == "__main__":
    main()
