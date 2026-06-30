"""
alberta_lobbyist_scraper.py
Daily incremental change analyzer with automated Gmail HTML digest mailing.
Includes advanced structural row-filtering to eliminate layout noise.
"""
import os
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
    password = os.environ.get("SMTP_PASSWORD")  # 16-character secure App Password
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

def execute_daily_scrape():
    print("Initiating incremental lobbyist monitoring check with sanitation filters...")
    
    if not os.path.exists(HISTORICAL_DATA_FILE):
        print(f"[FATAL] Reference historical ledger not found at destination: {HISTORICAL_DATA_FILE}")
        return
        
    historical_df = pd.read_csv(HISTORICAL_DATA_FILE)
    
    if "REGISTRATION NUMBER" in historical_df.columns:
        existing_tokens = set(historical_df["REGISTRATION NUMBER"].astype(str).tolist())
    else:
        print("[FATAL] Structural anomalies located in target column headers.")
        return

    new_records_captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        try:
            print(f"Navigating to live query baseline: {BASE_URL}")
            page.goto(BASE_URL, wait_until="networkidle")
            page.locator("text=Search Registry").first.click()
            page.wait_for_load_state("networkidle")
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
                print("[ERROR] Table context container frame could not be isolated.")
                browser.close()
                return

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
            
            if matrix and len(matrix) > 1:
                header_row = [str(cell).strip().upper() for cell in matrix[0]]
                data_start_idx = 1 if any("REGISTRATION" in col for col in header_row) else 0
                
                try:
                    reg_num_idx = header_row.index("REGISTRATION NUMBER")
                except ValueError:
                    reg_num_idx = 0
                    
                for idx in range(data_start_idx, len(matrix)):
                    # Sanitize structural spacing elements from raw browser cell values instantly
                    raw_row_data = matrix[idx]
                    row_data = [str(cell).replace("\n", " ").replace("\t", " ").strip() for cell in raw_row_data]
                    
                    if not any(row_data) or len(row_data) <= reg_num_idx:
                        continue
                        
                    # DATA VALIDATION GUARD: Drop layout summary lines and framework meta-headers completely
                    combined_row_text = "".join(row_data).upper()
                    if "FILING DATE" in combined_row_text or "1 - 15 OF" in combined_row_text or "VIEW" == row_data[0]:
                        continue
                        
                    live_token = str(row_data[reg_num_idx])
                    
                    # Ensure token matches a clean registry identifier format, skipping empty artifacts
                    if not live_token or "REGISTRATION" in live_token.upper():
                        continue
                    
                    if live_token not in existing_tokens:
                        print(f" -> Frontier Alert: Detected incoming record token: {live_token}")
                        
                        pdf_text = "No tracking details extracted from profile disclosure file"
                        try:
                            with context.expect_event("download", timeout=6000) as download_info:
                                winning_frame.evaluate("""(targetIndex) => {
                                    const tables = Array.from(document.querySelectorAll('table'));
                                    let bestTable = null;
                                    for (const table of tables) {
                                        if ((table.innerText || '').toLowerCase().includes('registration')) {
                                            bestTable = table; break;
                                        }
                                    }
                                    if (bestTable) {
                                        const trs = Array.from(bestTable.querySelectorAll('tr'));
                                        if (targetIndex < trs.length) {
                                            const cells = trs[targetIndex].querySelectorAll('td');
                                            if (cells.length > 0) {
                                                const finalCell = cells[cells.length - 1];
                                                const node = finalCell.querySelector('a, img') || finalCell;
                                                node.click();
                                            }
                                        }
                                    }
                                }""", idx)
                            
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
                        
        except Exception as e:
            print(f"Daily monitor process error: {str(e)}")
        finally:
            browser.close()

    if new_records_captured:
        print(f"Processing updates for {len(new_records_captured)} new entries...")
        
        visual_data_summary = []
        for record in new_records_captured:
            visual_data_summary.append({
                "Filing Date": record[0] if len(record) > 0 else "N/A",
                "Organization/Lobbyist": record[2] if len(record) > 2 else "N/A",
                "Client Name": record[3] if len(record) > 3 else "Direct Filer",
                "Registration Number": record[8] if len(record) > 8 else "N/A",
                "Type of Registration": record[11] if len(record) > 11 else "N/A"
            })
            
        summary_df = pd.DataFrame(visual_data_summary)
        html_table = summary_df.to_html(index=False, classes='table-style')
        
        email_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #333333; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; }}
                th {{ background-color: #1a73e8; color: white; padding: 12px; text-align: left; font-weight: 600; }}
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
        
        append_df = pd.DataFrame(new_records_captured, columns=historical_df.columns)
        append_df.to_csv(HISTORICAL_DATA_FILE, mode='a', header=False, index=False)
        print("Master historical tracking database successfully synced and extended.")
    else:
        print("No incoming additions identified inside the live registry front view. Database is synchronized.")

if __name__ == "__main__":
    execute_daily_scrape()
