"""
alberta_backfill.py
Comprehensive historical registry crawler with Token-Based Matching and Stateful Synchronization Locks.
"""
import os
import signal
import pandas as pd
from playwright.sync_api import sync_playwright

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_DATA_FILE = os.path.join(CURRENT_DIR, "alberta_lobbyists_historical.csv")
BASE_URL = "https://albertalobbyistregistry.ca/"

class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("PDF parsing took too long")

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
    print("Initializing frame-piercing Frontier Skip-Scanning pipeline with Stateful Synchronous Locking...")
    
    # Configure Unix alarm signal for synchronous execution timeouts
    signal.signal(signal.SIGALRM, timeout_handler)
    
    # Load previously processed records to enable intelligent skip-scanning fast-forwarding
    existing_tokens = set()
    if os.path.exists(HISTORICAL_DATA_FILE) and os.path.getsize(HISTORICAL_DATA_FILE) > 0:
        try:
            existing_df = pd.read_csv(HISTORICAL_DATA_FILE)
            if "REGISTRATION NUMBER" in existing_df.columns:
                existing_tokens = set(existing_df["REGISTRATION NUMBER"].astype(str).tolist())
            print(f"[RESUME] Found existing archive tracking file. Loaded {len(existing_tokens)} unique keys.")
        except Exception as e:
            print(f"Note: Could not parse existing historical data tracking sheet ({str(e)}). Starting fresh.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        global_headers = None
        page_number = 1
        fresh_pages_processed = 0
        MAX_FRESH_PAGES_PER_RUN = 40 
        
        try:
            print(f"Navigating to base endpoint: {BASE_URL}")
            page.goto(BASE_URL, wait_until="networkidle")
            
            print("Accessing the query portal...")
            page.locator("text=Search Registry").first.click()
            page.wait_for_load_state("networkidle")
            
            print("Triggering database initialization search...")
            page.locator("input#Search").click()
            page.wait_for_timeout(10000)
            
            winning_frame = None
            for frame in page.frames:
                try:
                    if frame.evaluate("() => document.querySelectorAll('table').length > 0"):
                        winning_frame = frame
                        break
                except Exception:
                    continue
                    
            if not winning_frame:
                print("Fatal Error: Could not locate the primary database iframe wrapper context.")
                browser.close()
                return

            # Main sequential pagination loop execution track
            while True:
                current_pagination_state = get_pagination_text(winning_frame)
                print(f"\n--- SCANNING DATA GRID: PAGE {page_number} ({current_pagination_state}) ---")
                
                matrix = winning_frame.evaluate("""() => {
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
                
                if not matrix or len(matrix) < 2:
                    print("No data matrix found on this page slice. Ending crawl loop.")
                    break
                    
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
                
                valid_rows_to_process = []
                contains_new_records = False
                
                for idx in range(data_start_idx, len(matrix)):
                    raw_row_data = matrix[idx]
                    row_data = [str(cell).replace("\n", " ").replace("\t", " ").strip() for cell in raw_row_data]
                    
                    if not any(row_data) or len(row_data) <= reg_num_idx:
                        continue
                        
                    combined_row_text = "".join(row_data).upper()
                    if "FILING DATE" in combined_row_text or "1 - 15 OF" in combined_row_text or "VIEW" == row_data[0]:
                        continue
                        
                    reg_token = str(row_data[reg_num_idx])
                    if not reg_token or "REGISTRATION" in reg_token.upper():
                        continue
                        
                    valid_rows_to_process.append((row_data, reg_token))
                    if reg_token not in existing_tokens:
                        contains_new_records = True

                if not valid_rows_to_process:
                    print(f" >> Page {page_number} contains only layout noise. Fast-forwarding link...")
                elif not contains_new_records:
                    print(f" >> [FAST-FORWARD] All {len(valid_rows_to_process)} records on Page {page_number} already cached. Skimming page...")
                else:
                    print(f" Isolated {len(valid_rows_to_process)} records on page {page_number}. Syncing unindexed targets...")
                    page_records = []
                    
                    for row_data, reg_token in valid_rows_to_process:
                        if reg_token in existing_tokens:
                            print(f"  -> [{reg_token}] already cached in ledger.")
                            continue
                            
                        print(f"  -> Extracting text details for frontier item: {reg_token}")
                        pdf_text = "No tracking details extracted from profile disclosure file"
                        
                        try:
                            # STATEFUL SYNCHRONIZATION LOCK: Binds the explicit download event channel before firing clicks
                            with context.expect_event("download", timeout=7000) as download_info:
                                winning_frame.evaluate("""(regNum) => {
                                    const tables = Array.from(document.querySelectorAll('table'));
                                    for (const table of tables) {
                                        const trs = Array.from(table.querySelectorAll('tr'));
                                        for (const tr of trs) {
                                            if (tr.innerText.includes(regNum)) {
                                                const cells = tr.querySelectorAll('td');
                                                if (cells.length > 0) {
                                                    const finalCell = cells[cells.length - 1];
                                                    const activationNode = finalCell.querySelector('a, button, img, span') || finalCell;
                                                    activationNode.click();
                                                    return true;
                                                }
                                            }
                                        }
                                    }
                                    return false;
                                }""", str(reg_token))
                                
                            # HALT EXECUTION: Wait explicitly for operating system disk write sync confirmation
                            download = download_info.value
                            temp_pdf_path = os.path.join(CURRENT_DIR, f"backfill_temp_{reg_token}.pdf")
                            download.save_as(temp_pdf_path)
                            
                            signal.alarm(8)
                            try:
                                from pypdf import PdfReader
                                reader = PdfReader(temp_pdf_path)
                                text_accumulator = []
                                for individual_page in reader.pages:
                                    page_content = individual_page.extract_text()
                                    if page_content:
                                        text_accumulator.append(page_content)
                                        
                                if text_accumulator:
                                    pdf_text = " ".join(text_accumulator).replace("\n", " ").strip()
                            except TimeoutException:
                                pdf_text = "PDF processing time limit exceeded - raw text unindexed"
                            finally:
                                signal.alarm(0)
                                
                            if os.path.exists(temp_pdf_path):
                                os.remove(temp_pdf_path)
                                
                        except Exception as download_error:
                            pdf_text = f"PDF Sync Skipped or download timed out: {str(download_error)}"
                        
                        base_row_list = list(row_data)
                        while len(base_row_list) < (len(global_headers) - 1):
                            base_row_list.append("")
                        if len(base_row_list) > (len(global_headers) - 1):
                            base_row_list = base_row_list[:len(global_headers) - 1]
                            
                        extended_record = base_row_list + [pdf_text]
                        page_records.append(extended_record)
                        
                        # Add a deliberate 1.5-second hard session cool-down.
                        # This clears the server's binary session cache before moving to the next row token.
                        page.wait_for_timeout(1500)
                    
                    if page_records:
                        chunk_df = pd.DataFrame(page_records, columns=global_headers)
                        cleaned_cols = [c for c in chunk_df.columns if "COLUMN_" in c or "VIEW" in c]
                        if cleaned_cols:
                            chunk_df = chunk_df.drop(columns=cleaned_cols)
                        
                        if not os.path.exists(HISTORICAL_DATA_FILE):
                            chunk_df.to_csv(HISTORICAL_DATA_FILE, index=False)
                        else:
                            chunk_df.to_csv(HISTORICAL_DATA_FILE, mode='a', header=False, index=False)
                        print(f"[CHECKPOINT] Saved Page {page_number} data additions to ledger file.")
                    
                    fresh_pages_processed += 1
                    if fresh_pages_processed >= MAX_FRESH_PAGES_PER_RUN:
                        print(f"\n[SYSTEM] Reached maximum processing threshold allotment ({MAX_FRESH_PAGES_PER_RUN} fresh pages).")
                        break
                
                # --- NATIVE ORACLE APEX INTERACTIVE REPORT PAGINATION HANDLING ---
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
                    page_number += 1
                    for check_attempt in range(30):
                        page.wait_for_timeout(500)
                        updated_pagination_state = get_pagination_text(winning_frame)
                        if updated_pagination_state != current_pagination_state and updated_pagination_state != "":
                            break
                else:
                    print("No subsequent data blocks found. Archive backfill fully complete!")
                    break
                    
        except Exception as pipeline_fault:
            print(f"Backfill stream execution halted by system fault: {str(pipeline_fault)}")
            
        finally:
            browser.close()

if __name__ == "__main__":
    backfill_historical_registry()
