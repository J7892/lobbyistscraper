"""
alberta_backfill.py
Standalone comprehensive historical registry crawler with automated browser recycling safeguards.
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
    print("Initializing frame-piercing deep archive backfill pipeline with recycling safeguards...")
    
    # Configure Unix alarm signal for synchronous execution timeouts
    signal.signal(signal.SIGALRM, timeout_handler)
    
    page_number = 1
    global_headers = None
    
    while True:
        # Load processed tokens dynamically on every browser session boot to enable seamless resume steps
        existing_tokens = set()
        if os.path.exists(HISTORICAL_DATA_FILE) and os.path.getsize(HISTORICAL_DATA_FILE) > 0:
            try:
                existing_df = pd.read_csv(HISTORICAL_DATA_FILE)
                if "REGISTRATION NUMBER" in existing_df.columns:
                    existing_tokens = set(existing_df["REGISTRATION NUMBER"].astype(str).tolist())
            except Exception:
                pass

        print(f"\n[SYSTEM] Launching fresh isolated browser environment session. Current page tracker: {page_number}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()
            
            try:
                page.goto(BASE_URL, wait_until="networkidle")
                page.locator("text=Search Registry").first.click()
                page.wait_for_load_state("networkidle")
                page.locator("input#Search").click()
                page.wait_for_timeout(12000)
                
                winning_frame = None
                for frame in page.frames:
                    try:
                        if frame.evaluate("() => document.querySelectorAll('table').length > 0"):
                            winning_frame = frame
                            break
                    except Exception:
                        continue
                        
                if not winning_frame:
                    print("[ERROR] Could not isolate table frame context. Re-attempting session boot...")
                    browser.close()
                    continue

                # Fast-forward the newly opened browser instance to our active working page split
                if page_number > 1:
                    print(f"[SYSTEM] Fast-forwarding browser session to active page target slice: {page_number}")
                    for ff_step in range(1, page_number):
                        winning_frame.evaluate("""() => {
                            const links = Array.from(document.querySelectorAll('a'));
                            const nextLink = links.find(l => (l.getAttribute('href') || '').includes('gReport.navigate') && 
                                           ((l.getAttribute('title') || '').toLowerCase().includes('next') || l.innerText.includes('>')));
                            if (nextLink) nextLink.click();
                        }""")
                        page.wait_for_timeout(2500)
                    print("[SYSTEM] Fast-forward positioning synchronized successfully.")

                # Process a fixed block of 15 pages before cycling the browser instance to kill memory leaks
                session_pages_processed = 0
                while session_pages_processed < 15:
                    current_pagination_state = get_pagination_text(winning_frame)
                    print(f"\n--- SCANNING DATA GRID: PAGE {page_number} ({current_pagination_state}) ---")
                    
                    matrix = winning_frame.evaluate("""() => {
                        const tables = Array.from(document.querySelectorAll('table'));
                        if (tables.length === 0) return null;
                        let bestTable = null; let maxScore = -1;
                        for (const table of tables) {
                            const text = (table.innerText || '').toLowerCase();
                            let score = 0;
                            if (text.includes('registration')) score += 15;
                            if (text.includes('filing')) score += 15;
                            const rows = Array.from(table.querySelectorAll('tr'));
                            if (rows.length >= 2) score += 20 + rows.length;
                            if (score > maxScore && rows.length >= 2) { maxScore = score; bestTable = table; }
                        }
                        if (!bestTable) return null;
                        return Array.from(bestTable.querySelectorAll('tr')).map(tr => 
                            Array.from(tr.querySelectorAll('th, td')).map(c => (c.innerText || '').trim())
                        ).filter(row => row.length > 0);
                    }""")
                    
                    if not matrix or len(matrix) < 2:
                        print("[SYSTEM] Reached the end of active database tables. Closing pipeline.")
                        browser.close()
                        return
                        
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
                    page_records = []
                    
                    for idx in range(data_start_idx, len(matrix)):
                        row_data = matrix[idx]
                        if not any(row_data): continue
                        
                        reg_token = row_data[reg_num_idx] if reg_num_idx < len(row_data) else f"token_{page_number}_{idx}"
                        current_item_num = idx - data_start_idx + 1
                        
                        if str(reg_token) in existing_tokens:
                            print(f" -> [{current_item_num}/{rows_in_batch}] Skim-skipping record {reg_token} (Already Indexed)")
                            continue
                            
                        print(f" -> [{current_item_num}/{rows_in_batch}] Downloading disclosure PDF for {reg_token}...")
                        pdf_text = "No tracking details extracted from profile disclosure file"
                        
                        try:
                            with context.expect_event("download", timeout=6000) as download_info:
                                winning_frame.evaluate("""(targetIndex) => {
                                    const tables = Array.from(document.querySelectorAll('table'));
                                    let bestTable = null; let maxScore = -1;
                                    for (const table of tables) {
                                        const text = (table.innerText || '').toLowerCase();
                                        let score = 0; if (text.includes('registration')) score += 15;
                                        const rows = Array.from(table.querySelectorAll('tr'));
                                        if (rows.length >= 2) score += rows.length;
                                        if (score > maxScore && rows.length >= 2) { maxScore = score; bestTable = table; }
                                    }
                                    if (bestTable) {
                                        const trs = Array.from(bestTable.querySelectorAll('tr'));
                                        if (targetIndex < trs.length) {
                                            const cells = trs[targetIndex].querySelectorAll('td');
                                            if (cells.length > 0) {
                                                const finalCell = cells[cells.length - 1];
                                                // PRECISION TARGETING: Find the absolute inner link anchor or image tag node directly
                                                const activationNode = finalCell.querySelector('a, href, img') || finalCell;
                                                activationNode.click();
                                            }
                                        }
                                    }
                                }""", idx)
                                
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
                                    if page_content: text_accumulator.append(page_content)
                                if text_accumulator:
                                    pdf_text = " ".join(text_accumulator).replace("\n", " ").strip()
                            except TimeoutException:
                                pdf_text = "PDF processing time limit exceeded - raw text unindexed"
                            finally:
                                signal.alarm(0)
                                
                            if os.path.exists(temp_pdf_path): os.remove(temp_pdf_path)
                                
                        except Exception as e:
                            print(f"    * Notice: Skipped/Timed Out row {reg_token}: {str(e)}")
                            pdf_text = "PDF entry data lookup skipped or document format unreadable"
                        
                        base_row_list = list(row_data)
                        while len(base_row_list) < (len(global_headers) - 1): base_row_list.append("")
                        if len(base_row_list) > (len(global_headers) - 1): base_row_list = base_row_list[:len(global_headers) - 1]
                        
                        page_records.append(base_row_list + [pdf_text])
                        page.wait_for_timeout(400)
                    
                    if page_records:
                        chunk_df = pd.DataFrame(page_records, columns=global_headers)
                        cleaned_cols = [c for c in chunk_df.columns if "COLUMN_" in c or "VIEW" in c]
                        if cleaned_cols: chunk_df = chunk_df.drop(columns=cleaned_cols)
                        
                        if not os.path.exists(HISTORICAL_DATA_FILE):
                            chunk_df.to_csv(HISTORICAL_DATA_FILE, index=False)
                        else:
                            chunk_df.to_csv(HISTORICAL_DATA_FILE, mode='a', header=False, index=False)
                        print(f"Incremental Checkpoint: Saved Page {page_number} changes to disk.")
                    
                    print("Clicking next page using targeted Oracle APEX engine hooks...")
                    has_next_page = winning_frame.evaluate("""() => {
                        const links = Array.from(document.querySelectorAll('a'));
                        const nextLink = links.find(l => {
                            const href = l.getAttribute('href') || '';
                            const text = (l.innerText || '').toLowerCase();
                            const img = l.querySelector('img');
                            const imgTitle = img ? (img.getAttribute('title') || img.getAttribute('alt') || '').toLowerCase() : '';
                            return href.includes('gReport.navigate') && (imgTitle.includes('next') || text.includes('next') || text.includes('>'));
                        });
                        if (nextLink) { nextLink.click(); return true; }
                        return false;
                    }""")
                    
                    if has_next_page:
                        page_number += 1
                        session_cycles_verified = False
                        for check_attempt in range(30):
                            page.wait_for_timeout(500)
                            updated_state = get_pagination_text(winning_frame)
                            if updated_state != current_pagination_state and updated_state != "":
                                session_cycles_verified = True
                                break
                        if not session_cycles_verified:
                            print("[WARNING] AJAX boundary string refresh missed.")
                        session_pages_processed += 1
                    else:
                        print("No further pagination structures detected. Backfill sequence finished.")
                        browser.close()
                        return
                        
                print("[SYSTEM] Target session threshold reached. Recycling browser process to protect pipes...")
                browser.close()
                
            except Exception as loop_fault:
                print(f"[SYSTEM CRASH] Active session environment collapsed: {str(loop_fault)}")
                try: browser.close()
                except Exception: pass
                page.wait_for_timeout(5000)

if __name__ == "__main__":
    backfill_historical_registry()
