"""
alberta_lobbyist_scraper.py
"""
import os
import pandas as pd
from playwright.sync_api import sync_playwright

DATA_FILE = "alberta_lobbyists.csv"
URL = "https://www.albertalobbyistregistry.ca/apex/f?p=171:9996:0::NO:::"

def fetch_registry_data():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"Navigating to {URL}...")
        page.goto(URL, wait_until="networkidle")
        
        html_content = page.content()
        browser.close()
        
        try:
            # Pandas read_html automatically finds all <table> elements
            tables = pd.read_html(html_content)
        except ValueError:
            print("No tables found on the page.")
            return None
            
        if not tables:
            return None
            
        # The primary registry data is reliably the largest table on the page
        data_table = max(tables, key=lambda t: len(t))
        
        # Clean up column names for consistency
        data_table.columns = [str(col).strip().upper() for col in data_table.columns]
        
        return data_table

def identify_changes(old_df, new_df):
    # Try to find an appropriate ID column to track entities across runs
    possible_id_cols = [col for col in new_df.columns if "NUMBER" in col or "ID" in col]
    
    if not possible_id_cols:
        print("Warning: Could not find a definitive ID column. Using row index as a fallback.")
        id_col = new_df.columns[0]
    else:
        id_col = possible_id_cols[0]
        
    print(f"Tracking entities using the '{id_col}' column.")
    
    # Cast to string to prevent mismatch errors between runs
    old_df[id_col] = old_df[id_col].astype(str)
    new_df[id_col] = new_df[id_col].astype(str)
    
    # 1. New Registrations
    new_records = new_df[~new_df[id_col].isin(old_df[id_col])]
    
    # 2. Deregistrations / Removals
    removed_records = old_df[~old_df[id_col].isin(new_df[id_col])]
    
    # 3. Changes in existing records (e.g., Status changed to "Terminated")
    common_ids = new_df[new_df[id_col].isin(old_df[id_col])][id_col]
    
    old_common = old_df[old_df[id_col].isin(common_ids)].set_index(id_col).sort_index()
    new_common = new_df[new_df[id_col].isin(common_ids)].set_index(id_col).sort_index()
    
    changes = []
    for idx in common_ids:
        # Fill NAs to avoid nan != nan evaluations triggering false positives
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
        print("Failed to extract data. The website structure may have changed.")
        return
        
    print(f"Extracted {len(current_df)} current registry rows.")
    
    # If a database file exists, compare current state to previous state
    if os.path.exists(DATA_FILE):
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
        
    # Overwrite the old database with the new state
    current_df.to_csv(DATA_FILE, index=False)
    print(f"\nState saved to {DATA_FILE}. Run this script again tomorrow to detect changes.")

if __name__ == "__main__":
    main()
