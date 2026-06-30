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
            
            # Navigate to the portal via the known menu path
            print("Accessing the Search Registry portal...")
            page.locator("text=Search Registry").first.click()
            page.wait_for_load_state("networkidle")
            
            # Trigger the search
            print("Triggering database query...")
            page.locator("input#Search").click()
            
            # DYNAMIC WAIT: Instead of a fixed sleep, we wait for a row element to appear
            print("Waiting for grid rows to render dynamically...")
            # APEX tables often contain 't-Report-report' or 'a-IRR-table'
            page.wait_for_selector(".t-Report-report, .a-IRR-table", timeout=20000)
            # Give an extra 2s for the data to fully populate inside the table
            page.wait_for_timeout(2000)
            
        except Exception as e:
            msg = f"Automation failed: {str(e)}"
            diagnostic_holder["reason"] = msg
            browser.close()
            return None
            
        print("Extracting data...")
        matrix = page.evaluate("""() => {
            // Target the APEX result container specifically
            const table = document.querySelector('.t-Report-report table') || document.querySelector('.a-IRR-table');
            if (!table) return null;
            
            const rows = Array.from(table.querySelectorAll('tr'));
            return rows.map(r => Array.from(r.querySelectorAll('th, td')).map(c => c.innerText ? c.innerText.trim() : ''));
        }""")
        
        browser.close()
        
        if not matrix or len(matrix) < 2:
            diagnostic_holder["reason"] = "Grid container found, but no data rows detected."
            return None
            
        header = [str(c).strip().upper() for c in matrix[0]]
        return pd.DataFrame([r for r in matrix[1:] if any(r)], columns=header)

# ... (rest of your identify_changes and main functions remain the same)
