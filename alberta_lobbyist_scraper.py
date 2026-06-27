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
            
            # --- THE TELEPORTATION FIX ---
            # We are not clicking buttons. We are calling the APEX navigation function directly.
            print("Directly invoking navigation to the Search Registry portal...")
            page.evaluate("apex.navigation.redirect('f?p=101:SEARCH_REGISTRY')")
            
            print("Waiting for the registry database to render...")
            page.wait_for_timeout(10000)
            
            # If the search results aren't auto-loaded, trigger a silent search
            print("Ensuring grid is populated...")
            page.evaluate("""() => {
                const searchBtn = document.querySelector('button[aria-label="Search"], input[value="Search"]');
                if (searchBtn) searchBtn.click();
            }""")
            page.wait_for_timeout(10000)
            
        except Exception as e:
            msg = f"Navigation failed: {str(e)}"
            diagnostic_holder["reason"] = msg
            page.screenshot(path="debug_screenshot.png", full_page=True)
            browser.close()
            return None
            
        page.screenshot(path="debug_screenshot.png", full_page=True)
        
        print("Extracting live data rows natively from the browser screen...")
        matrix = page.evaluate("""() => {
            const table = document.querySelector('table') || document.querySelector('.a-IRR-table');
            if (!table) return null;
            
            const rows = Array.from(table.querySelectorAll('tr'));
            return rows.map(r => Array.from(r.querySelectorAll('th, td')).map(c => c.innerText ? c.innerText.trim() : ''));
        }""")
        
        browser.close()
        
        if not matrix or len(matrix) < 2:
            diagnostic_holder["reason"] = "The browser arrived at the page, but failed to extract the registry grid."
            return None
            
        header_row = [str(cell).strip().upper() for cell in matrix[0]]
        cleaned_rows = [row for row in matrix[1:] if any(row)]
        
        return pd.DataFrame(cleaned_rows, columns=header_row)

def identify_changes(old_df, new_df):
    id_col = next((c for c in new_df.columns if "ID" in c or "NUMBER" in c), new_df.columns[0])
    old_df[id_col], new_df[id_col] = old_df[id_col].astype(str), new_df[id_col].astype(str)
    
    new_recs = new_df[~new_df[id_col].isin(old_df[id_col])]
    removed_recs = old_df[~old_df[id_col].isin(new_df[id_col])]
    
    return new_recs, removed_recs, []

def main():
    diagnostic_holder = {"reason": "Unknown error."}
    current_df = fetch_registry_data(diagnostic_holder)
    
    if current_df is None:
        pd.DataFrame([{"STATUS": "FAILED", "LOG": diagnostic_holder["reason"]}]).to_csv(DATA_FILE, index=False)
        return
        
    if os.path.exists(DATA_FILE):
        prev_df = pd.read_csv(DATA_FILE)
        new, rem, _ = identify_changes(prev_df, current_df)
        print(f"Detected {len(new)} new registrations and {len(rem)} removals.")
        
    current_df.to_csv(DATA_FILE, index=False)

if __name__ == "__main__":
    main()
