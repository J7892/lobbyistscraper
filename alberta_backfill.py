"""
alberta_backfill.py
Standalone comprehensive historical registry crawler using the 15-row pagination sequence.
"""
import os
import pandas as pd
from playwright.sync_api import sync_playwright

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_DATA_FILE = os.path.join(CURRENT_DIR, "alberta_lobbyists_historical.csv")
BASE_URL = "https://albertalobbyistregistry.ca/"

def get_pagination_text(frame):
    """Extracts the active row boundaries text to monitor AJAX updates safely."""
    try:
        return frame.evaluate("""() => {
            const el = document.querySelector('span.fielddata, td.pagination, .pagination');
            return el ? el.innerText.trim() : '';
        }""")
    except Exception:
        return ""

def backfill_historical_registry():
    print("Initializing frame-piercing deep archive backfill pipeline...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        all_collected_records = []
        global_headers = None
        page_number = 1
        
        try:
            print(f"Navigating to base endpoint: {BASE_URL}")
            page.goto(BASE_URL, wait_until="networkidle")
            
            print("Accessing the query portal...")
            page.locator("text=Search Registry").first.click()
            page.wait_for_load_state("networkidle")
            
            print("Triggering database initialization search...")
            page.locator("input#Search").click()
            
            print("Waiting 15 seconds for search results and frames to fully generate...")
            page.wait_for_timeout(15000)
            
            # Main sequential pagination loop execution track
            while True:
                # Dynamically locate the data matrix and frame on every loop cycle
                matrix = None
                max_rows = 0
                winning_frame = None
                
                for frame in page.frames:
                    try:
                        frame_matrix = frame.evaluate("""() => {
                            const tables = Array.from(document.querySelectorAll('table'));
                            if (tables.length === 0) return null;
                            
                            let bestTable = null;
                            let maxScore = -1;
                            
                            for (const table of tables) {
                                const text = (table.innerText || '').toLowerCase();
                                let score = 0;
                                
                                if (text.includes('registration')) score += 15;
                                if (text.includes('filing')) score += 15;
                                if (text.includes('status')) score += 10;
                                if (text.includes('lobbyist')) score += 15;
                                if (text.includes('organization')) score += 10;
                                
                                const rows = Array.from(table.querySelectorAll('tr'));
                                if (rows.length >= 2) {
                                    const sampleCells = rows[0].querySelectorAll('th, td').length;
                                    if (sampleCells >= 4) score += 20;
                                    score += rows.length;
                                }
                                
                                if (score > maxScore && rows.length >= 2) {
                                    maxScore = score;
                                    bestTable = table;
                                }
                            }
                            
                            if (!bestTable) return null;
                            
                            const trs = Array.from(bestTable.querySelectorAll('tr'));
                            return trs.map(tr => 
                                Array.from(tr.querySelectorAll('th, td')).map(c => (c.innerText || '').trim())
                            ).filter(row => row.length > 0);
                        }""")
                        
                        if frame_matrix and len(frame_matrix) > max_rows:
                            max_rows = len(frame_matrix)
                            matrix = frame_matrix
                            winning_frame = frame
                    except Exception:
                        continue

                if not matrix or len(matrix) < 2 or not winning_frame:
                    print("No active data container found across any frame contexts. Ending crawl run.")
                    break
                    
                current_pagination_state = get_pagination_text(winning_frame)
                print(f"\n--- PROCESSING DATA CHUNK: PAGE {page_number} ({current_pagination_state}) ---")
                
                # Align structural table column tags
                header_row = [str(cell).strip().upper() for cell in matrix[0]]
                is_header = any("REGISTRATION" in col or "FILING" in col for col in header_row)
                data_start_idx = 1 if is_header else 0
                
                if global_headers is None:
                    global_headers = header_row if is_header else [f"FIELD_{i}" for i in range(len(matrix[0]))]
                    if "EXTRACTED_PDF_DETAILS" not in global_headers:
                        global_headers.append("EXTRACTED_PDF_DETAILS")
                        
                try:
                    reg_num_idx = global_headers.index("REGISTRATION NUMBER")
                except ValueError:
                    reg_num_idx = 0
                
                rows_in_batch = len(matrix) - data_start_idx
                print(f"Isolated {rows_in_batch} records on page {page_number}. Pulling inline disclosure PDFs...")
                
                # Execute sequential row-by-row clicks inside the current page view
                for idx in range(data_start_idx, len(matrix)):
                    row_data = matrix[idx]
                    if not any(row_data):
                        continue
                        
                    reg_token = row_data[reg_num_idx] if reg_num_idx < len(row_data) else f"token_{page_number}_{idx}"
                    current_item_num = idx - data_start_idx + 1
                    print(f" -> Processing disclosure form text [{current_item_num}/{rows_in_batch}]: Record ID {reg_token}")
                    
                    pdf_text = "No tracking details extracted from profile disclosure file"
                    
                    try:
                        # Synchronized row click routine targeting the scored table matrix
                        with context.expect_event("download", timeout=5000) as download_info:
                            winning_frame.evaluate("""(targetIndex) => {
                                const tables = Array.from(document.querySelectorAll('table'));
                                let bestTable = null;
                                let maxScore = -1;
                                
                                for (const table of tables) {
                                    const text = (table.innerText || '').toLowerCase();
                                    let score = 0;
                                    
                                    if (text.includes('registration')) score += 15;
                                    if (text.includes('filing')) score += 15;
                                    if (text.includes('status')) score += 10;
                                    if (text.includes('lobbyist')) score += 15;
                                    if (text.includes('organization')) score += 10;
                                    
                                    const rows = Array.from(table.querySelectorAll('tr'));
                                    if (rows.length >= 2) {
                                        const sampleCells = rows[0].querySelectorAll('th, td').length;
                                        if (sampleCells >= 4) score += 20;
                                        score += rows.length;
                                    }
                                    
                                    if (score > maxScore && rows.length >= 2) {
                                        maxScore = score;
                                        bestTable = table;
                                    }
                                }
                                
                                if (bestTable) {
                                    const trs = Array.from(bestTable.querySelectorAll('tr'));
                                    if (targetIndex < trs.length) {
                                        const cells = trs[targetIndex].querySelectorAll('td');
                                        if (cells.length > 0) {
                                            const finalCell = cells[cells.length - 1];
                                            const activationNode = finalCell.querySelector('a, button, img, span') || finalCell;
                                            activationNode.click();
                                        }
                                    }
                                }
                            }""", idx)
                            
                        download = download_info.value
                        temp_pdf_path = os.path.join(CURRENT_DIR, f"backfill_temp_{reg_token}.pdf")
                        download.save_as(temp_pdf_path)
                        
                        # Process target binary text contents to continuous string structures
                        from pypdf import PdfReader
                        reader = PdfReader(temp_pdf_path)
                        text_accumulator = []
                        for individual_page in reader.pages:
                            page_content = individual_page.extract_text()
                            if page_content:
                                text_accumulator.append(page_content)
                                
                        if text_accumulator:
                            pdf_text = " ".join(text_accumulator).replace("\n", " ").strip()
                            
                        if os.path.exists(temp_pdf_path):
                            os.remove(temp_pdf_path)
                            
                    except Exception as download_error:
                        print(f"    * Notice: Download skipped or timed out for token {reg_token}: {str(download_error)}")
                        pdf_text = "PDF entry data lookup skipped or document format unreadable"
                    
                    # Normalize formatting arrays before storage pushes
                    base_row_list = list(row_data)
                    while len(base_row_list) < (len(global_headers) - 1):
                        base_row_list.append("")
                    if len(base_row_list) > (len(global_headers) - 1):
                        base_row_list = base_row_list[:len(global_headers) - 1]
                        
                    extended_record = base_row_list + [pdf_text]
                    all_collected_records.append(extended_record)
                    
                    # Brief timeout throttle protects network session tokens
                    page.wait_for_timeout(400)
                
                # --- NATIVE ORACLE APEX INTERACTIVE REPORT PAGINATION HANDLING ---
                print("Clicking next page using targeted Oracle APEX engine hooks...")
                has_next_page = winning_frame.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const nextLink = links.find(l => {
                        const href = l.getAttribute('href') || '';
                        const text = (l.innerText || '').toLowerCase();
                        const img = l.querySelector('img');
                        const imgTitle = img ? (img.getAttribute('title') || img.getAttribute('alt') || '').toLowerCase() : '';
                        
                        return href.includes('gReport.navigate') && 
                               (imgTitle.includes('next') || text.includes('next') || text.includes('>'));
                    });
                    if (nextLink) {
                        nextLink.click();
                        return true;
                    }
                    return false;
                }""")
                
                if has_next_page:
                    print("Next page action fired. Waiting for AJAX DOM updates to cycle...")
                    page_number += 1
                    
                    # Watch the DOM until the pagination row string changes state safely
                    is_updated = False
                    for check_attempt in range(30):
                        page.wait_for_timeout(500)
                        updated_pagination_state = get_pagination_text(winning_frame)
                        if updated_pagination_state != current_pagination_state and updated_pagination_state != "":
                            is_updated = True
                            break
                    
                    if not is_updated:
                        print("Warning: AJAX table container failed to refresh. Forcing cycle breakthrough.")
                else:
                    print("No further pagination structures detected. Archive sweep sequence finished.")
                    break
                    
        except Exception as pipeline_fault:
            print(f"Backfill stream execution halted by system fault: {str(pipeline_fault)}")
            
        finally:
            browser.close()
            
        if all_collected_records:
            print(f"\nCompiling dataset baseline containing {len(all_collected_records)} parsed elements...")
            historical_df = pd.DataFrame(all_collected_records, columns=global_headers)
            
            cleaned_cols = [c for c in historical_df.columns if "COLUMN_" in c or "VIEW" in c]
            if cleaned_cols:
                historical_df = historical_df.drop(columns=cleaned_cols)
                
            historical_df.to_csv(HISTORICAL_DATA_FILE, index=False)
            print(f"Success! Master archive written safely to absolute ledger destination: {HISTORICAL_DATA_FILE}")
        else:
            print("System finished crawl run with zero collected text matrices.")

if __name__ == "__main__":
    backfill_historical_registry()
