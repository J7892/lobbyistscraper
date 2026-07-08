"""
alberta_lobbyist_scraper.py
Daily incremental change analyzer with automated Gmail HTML digest mailing.
Cleaned and optimized: Interface generation stripped out to support fully decoupled dynamic architectures.
"""
import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pandas as pd
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_DATA_FILE = os.path.join(CURRENT_DIR, "alberta_lobbyists_historical.csv")
BASE_URL = "https://albertalobbyistregistry.ca/"

def send_email_digest(html_content, subject_text="Daily Lobbyist Registry Update"):
    """Connects to Gmail SMTP backbone to transmit the compiled HTML dataset."""
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("NOTIFY_EMAIL")
    
    if not all([username, password, recipient]):
        print("[WARNING] Email credentials missing from GitHub secrets environment. Skipping notification.")
        return

    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject_text
    msg["From"] = username
    msg["To"] = recipient

    msg.attach(MIMEText(html_content, "html"))

    try:
        print(f"Opening secure encrypted transport channel to {smtp_server}...")
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(username, recipient, msg.as_string())
        print(f"Success! Daily update digest sent safely to target address: {recipient}")
    except Exception as email_fault:
        print(f"[ERROR] Mail pipeline transmission dropped: {str(email_fault)}")

def extract_pdf_text(pdf_path):
    """Parses binary disclosure files to unified text layouts."""
    try:
        reader = PdfReader(pdf_path)
        text_accumulator = []
        for individual_page in reader.pages:
            content = individual_page.extract_text()
            if content:
                text_accumulator.append(content)
        return " ".join(text_accumulator).replace("\n", " ").strip() if text_accumulator else ""
    except Exception:
        return ""

def get_pagination_text(frame):
    """Extracts active row boundaries text to monitor AJAX page transitions safely."""
    try:
        return frame.evaluate("""() => {
            const selectors = ['.a-IRR-pagination-label', '.a-IRR-pagination', 'span.fielddata', 'td.pagination'];
            for (const selector of selectors) {
                const el = document.querySelector(selector);
                if (el && el.innerText.trim()) return el.innerText.trim();
            }
            return '';
        }""")
    except Exception:
        return ""

def execute_daily_scrape():
    print("Initiating incremental multi-page lobbyist monitoring check with Composite Keys...")
    
    if not os.path.exists(HISTORICAL_DATA_FILE):
        print(f"[FATAL] Reference historical ledger not found at destination: {HISTORICAL_DATA_FILE}")
        sys.exit(1)
        
    historical_df = pd.read_csv(HISTORICAL_DATA_FILE)
    
    if all(col in historical_df.columns for col in ["REGISTRATION NUMBER", "FILING DATE", "TYPE OF REGISTRATION"]):
        existing_signatures = set((
            historical_df["REGISTRATION NUMBER"].astype(str).str.strip() + "_" +
            historical_df["FILING DATE"].astype(str).str.strip() + "_" +
            historical_df["TYPE OF REGISTRATION"].astype(str).str.strip()
        ).tolist())
        print(f"[LOADED] Found master archive. Hashed {len(existing_signatures)} unique historical filing events.")
    else:
        print("[FATAL] Structural anomalies located in target column headers.")
        sys.exit(1)

    new_records_captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        try:
            print(f"Navigating to live query baseline: {BASE_URL}")
            page.goto(BASE_URL, wait_until="networkidle")
            page.locator("text=Search Registry").first.click()
            page.wait_for_load_state("networkidle")
            page.locator("input#Search").click()
            
            print("Waiting dynamically for database grid iframe to initialize and populate...")
            winning_frame = None
            for attempt in range(60): 
                for frame in page.frames:
                    try:
                        if frame.evaluate("() => document.querySelectorAll('table').length > 0"):
                            if frame.evaluate("() => document.body.innerText.toLowerCase().includes('registration')"):
                                winning_frame = frame
                                break
                    except Exception:
                        continue
                if winning_frame:
                    break
                page.wait_for_timeout(500)
            
            if not winning_frame:
                print("[FATAL ERROR] Table context container frame could not be isolated. Raising flag.")
                page.screenshot(path="debug_screenshot.png")
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                browser.close()
                sys.exit(1)

            print("[SUCCESS] Isolated active data streaming frame. Entering processing channel.")
            page_number = 1
            last_first_token = None
            stale_page_retries = 0

            # Dynamic sequential pagination tracking loop
            while True:
                matrix = winning_frame.evaluate("""() => {
                    const tables = Array.from(document.querySelectorAll('table'));
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
                    print("No data matrix found on this page slice. Exiting pagination loop.")
                    break

                header_row = [str(cell).strip().upper() for cell in matrix[0]]
                data_start_idx = 1 if any("REGISTRATION" in col for col in header_row) else 0
                
                reg_num_idx = next((i for i, col in enumerate(header_row) if "REGISTRATION" in col and "NUMBER" in col), 8)
                filing_date_idx = next((i for i, col in enumerate(header_row) if "FILING" in col and "DATE" in col), 0)
                type_reg_idx = next((i for i, col in enumerate(header_row) if "TYPE" in col and "REGISTRATION" in col), 11)

                this_page_first_token = None
                for idx in range(data_start_idx, len(matrix)):
                    raw_row_data = matrix[idx]
                    row_data = [str(cell).replace("\n", " ").replace("\t", " ").strip() for cell in raw_row_data]
                    if len(row_data) > reg_num_idx:
                        token_candidate = str(row_data[reg_num_idx])
                        if token_candidate and "REGISTRATION" not in token_candidate.upper():
                            this_page_first_token = token_candidate
                            break

                if last_first_token and this_page_first_token == last_first_token:
                    stale_page_retries += 1
                    if stale_page_retries > 10:
                        print(" [FATAL] Pagination event failed to shift browser DOM data stream. Breaking.")
                        sys.exit(1)
                    print(f" >> [AJAX DELAY] Waiting for interface update (Attempt {stale_page_retries}/10)...")
                    page.wait_for_timeout(1500)
                    continue

                stale_page_retries = 0
                current_pagination_state = get_pagination_text(winning_frame)
                print(f"\n--- SCRAPER ACTIVE: PAGE {page_number} ({current_pagination_state}) ---")

                valid_rows_to_process = []
                contains_new_records = False

                for idx in range(data_start_idx, len(matrix)):
                    raw_row_data = matrix[idx]
                    row_data = [str(cell).replace("\n", " ").replace("\t", " ").strip() for cell in raw_row_data]
                    
                    if not any(row_data) or len(row_data) <= max(reg_num_idx, filing_date_idx, type_reg_idx):
                        continue
                        
                    combined_row_text = "".join(row_data).upper()
                    if "FILING DATE" in combined_row_text or "1 - 15 OF" in combined_row_text or "VIEW" == row_data[0]:
                        continue
                        
                    live_token = str(row_data[reg_num_idx]).strip()
                    live_date = str(row_data[filing_date_idx]).strip()
                    live_type = str(row_data[type_reg_idx]).strip()
                    
                    if not live_token or "REGISTRATION" in live_token.upper():
                        continue

                    row_signature = f"{live_token}_{live_date}_{live_type}"

                    valid_rows_to_process.append((row_data, live_token, row_signature))
                    if row_signature not in existing_signatures:
                        contains_new_records = True

                if valid_rows_to_process and not contains_new_records:
                    print(f" >> [CATCH-UP COMPLETE] Hit baseline records on Page {page_number}. Halting search cleanly.")
                    break

                if contains_new_records:
                    for row_data, live_token, row_signature in valid_rows_to_process:
                        if row_signature in existing_signatures:
                            continue
                            
                        print(f"  -> Frontier Alert: Syncing brand-new filing update: {row_signature}")
                        pdf_text = "No tracking details extracted from profile disclosure file"
                        
                        try:
                            with context.expect_event("download", timeout=6000) as download_info:
                                winning_frame.evaluate("""(regNum) => {
                                    const trs = Array.from(document.querySelectorAll('tr'));
                                    for (const tr of trs) {
                                        if (tr.querySelector('table')) continue;
                                        const cells = Array.from(tr.querySelectorAll('td, th'));
                                        const match = cells.some(c => (c.innerText || '').trim() === regNum || (c.innerText || '').includes(regNum));
                                        
                                        if (match) {
                                            const tdCells = tr.querySelectorAll('td');
                                            if (tdCells.length > 0) {
                                                const finalCell = tdCells[tdCells.length - 1];
                                                const node = finalCell.querySelector('a, button, img, span') || finalCell;
                                                node.click();
                                                return true;
                                            }
                                        }
                                    }
                                    return false;
                                }""", str(live_token))
                            
                            download = download_info.value
                            temp_path = os.path.join(CURRENT_DIR, f"daily_temp_{live_token}.pdf")
                            download.save_as(temp_path)
                            pdf_text = extract_pdf_text(temp_path)
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception as click_err:
                            print(f"      * Could not download details for {live_token}: {str(click_err)}")
                            
                        base_row_list = list(row_data)
                        while len(base_row_list) < len(historical_df.columns) - 1:
                            base_row_list.append("")
                        base_row_list = base_row_list[:len(historical_df.columns) - 1]
                        
                        full_record_entry = base_row_list + [pdf_text]
                        new_records_captured.append(full_record_entry)
                        
                        page.wait_for_timeout(1500)

                if this_page_first_token:
                    last_first_token = this_page_first_token

                has_next_page = winning_frame.evaluate("""() => {
                    const apexNextBtn = document.querySelector('button[data-pagination="next"], .a-IRR-button--pagination[title*="Next"]');
                    if (apexNextBtn) { apexNextBtn.click(); return true; }
                    const links = Array.from(document.querySelectorAll('a'));
                    const nextLink = links.find(l => {
                        const href = l.getAttribute('href') || '';
                        const text = (l.innerText || '').trim().toLowerCase();
                        return href.includes('gReport.navigate') && (text === '>' || text === 'next');
                    });
                    if (nextLink) { nextLink.click(); return true; }
                    return false;
                }""")
                
                if has_next_page:
                    page_number += 1
                    page.wait_for_timeout(1000)
                else:
                    print("Reached end of registry list index completely.")
                    break
            
            # --- OUTPUT DESPATCH & RE-COMPILATION CHANNEL ---
            if new_records_captured:
                new_df = pd.DataFrame(new_records_captured, columns=historical_df.columns)
                
                display_df = new_df.copy()
                if "EXTRACTED_PDF_DETAILS" in display_df.columns:
                    display_df["EXTRACTED_PDF_DETAILS"] = display_df["EXTRACTED_PDF_DETAILS"].str.slice(0, 180) + "..."
                
                html_table = display_df.to_html(index=False, classes="dataframe")
                
                email_body = f"""
                <html>
                <head>
                    <style>
                        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #333333; line-height: 1.5; }}
                        table.dataframe {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; }}
                        th {{ background-color: #1a73e8; color: white; border: 1px solid #1a73e8; padding: 12px; text-align: left; font-weight: 600; }}
                        td {{ border: 1px solid #e0e0e0; padding: 10px; }}
                        tr:nth-child(even) {{ background-color: #f8f9fa; }}
                        .alert-header {{ color: #1a73e8; font-weight: bold; font-size: 20px; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }}
                    </style>
                </head>
                <body>
                    <div class="alert-header">Alberta Lobbyist Registry: New Disclosures Located</div>
                    <p>The daily monitor pipeline isolated the following brand-new filings within the live index:</p>
                    {html_table}
                    <br>
                    <p style="font-size: 11px; color: #888888; border-top: 1px solid #eeeeee; padding-top: 8px;">
                        This is an automated report delivered securely via your automated GitHub Actions infrastructure pipeline.
                    </p>
                </body>
                </html>
                """
                
                send_email_digest(email_body, subject_text=f"Alert: {len(new_records_captured)} New Alberta Lobbyist Registrations Detected")
                
                consolidated_df = pd.concat([new_df, historical_df], ignore_index=True)
                consolidated_df.to_csv(HISTORICAL_DATA_FILE, index=False)
                print(f"[SUCCESS] Prepended {len(new_records_captured)} new files to top of ledger and triggered email.")
            else:
                print("[IDLE] Index clean. 0 new disclosures discovered today.")
                        
        except Exception as e:
            print(f"[CRITICAL ERROR] Daily monitor execution fault: {str(e)}")
            page.screenshot(path="debug_screenshot.png")
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            browser.close()
            sys.exit(1)
        finally:
            browser.close()

if __name__ == "__main__":
    execute_daily_scrape()
