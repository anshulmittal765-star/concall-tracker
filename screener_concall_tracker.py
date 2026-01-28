#!/usr/bin/env python3
"""
Screener.in Concall Tracker - ENHANCED VERSION
With: Rate limiting, Email notifications, Watchlist colors, Optimized extraction
"""

import os
import sys
import time
import re
import base64
import json
import hashlib
import smtplib
from datetime import datetime, timedelta
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pdfplumber
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ============================================================================
# CONFIGURATION
# ============================================================================

# Environment variables
SCREENER_USERNAME = os.getenv('SCREENER_USERNAME')
SCREENER_PASSWORD = os.getenv('SCREENER_PASSWORD')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID')
GOOGLE_CREDENTIALS_BASE64 = os.getenv('GOOGLE_CREDENTIALS_BASE64')

# Email configuration (optional)
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'
EMAIL_USERNAME = os.getenv('EMAIL_USERNAME', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_TO = os.getenv('EMAIL_TO', EMAIL_USERNAME)

# Watchlist URLs (customize these!)
WATCHLISTS = {
    "My Stonks": {
        "url": os.getenv('MY_STONKS_WATCHLIST_URL', ''),
        "color": "11"  # Tomato
    },
    "Core Watchlist": {
        "url": os.getenv('CORE_WATCHLIST_URL', ''),
        "colors": ["4", "6", "5"]  # Flamingo, Tangerine, Banana - rotates
    }
}

# Rate limiting
PDF_DOWNLOAD_DELAY = 0.5  # seconds between downloads
MAX_RETRIES = 2
REQUEST_TIMEOUT = 15

# ============================================================================
# UTILITIES
# ============================================================================

def get_requests_session():
    """Create requests session with retry logic"""
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def normalize_company_name(name):
    """Normalize company name for matching"""
    name = name.lower().strip()
    for suffix in [' ltd', ' limited', ' pvt', ' private', ' inc', ' corp', ' llp', '.']:
        name = name.replace(suffix, '')
    return ' '.join(name.split())

# ============================================================================
# SELENIUM & SCRAPING
# ============================================================================

def setup_selenium():
    """Configure Selenium WebDriver"""
    print("Setting up Selenium WebDriver...")
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    return webdriver.Chrome(options=options)

def login_to_screener(driver):
    """Login to Screener.in"""
    print("Logging into Screener.in...")
    try:
        driver.get('https://www.screener.in/login/')
        
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.NAME, 'username')))
        
        driver.find_element(By.NAME, 'username').send_keys(SCREENER_USERNAME)
        driver.find_element(By.NAME, 'password').send_keys(SCREENER_PASSWORD)
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        
        time.sleep(3)
        
        if "login" in driver.current_url.lower():
            print("❌ Login failed!")
            return False
        
        print("✅ Login successful!")
        return True
        
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False

def scrape_watchlist(driver, watchlist_url):
    """Scrape companies from a watchlist"""
    if not watchlist_url:
        return set()
    
    try:
        driver.get(watchlist_url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
        )
        
        companies = set()
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        for row in rows:
            try:
                name_cell = row.find_element(By.CSS_SELECTOR, "td a")
                company_name = name_cell.text.strip()
                if company_name:
                    companies.add(normalize_company_name(company_name))
            except:
                continue
        
        return companies
    except:
        return set()

def scrape_all_watchlists(driver):
    """Scrape all configured watchlists"""
    print("\n📋 Scraping watchlists...")
    watchlists = {}
    
    for name, config in WATCHLISTS.items():
        url = config.get('url', '')
        if url:
            companies = scrape_watchlist(driver, url)
            watchlists[name] = companies
            print(f"  {name}: {len(companies)} companies")
        else:
            watchlists[name] = set()
    
    return watchlists

def get_watchlist_color(company, watchlists, color_counter):
    """Get calendar color for a company based on watchlist"""
    company_norm = normalize_company_name(company)
    
    # Check My Stonks first (highest priority)
    if "My Stonks" in watchlists:
        for wl_company in watchlists["My Stonks"]:
            if (company_norm == wl_company or 
                company_norm in wl_company or 
                wl_company in company_norm):
                return WATCHLISTS["My Stonks"]["color"]
    
    # Check Core Watchlist
    if "Core Watchlist" in watchlists:
        for wl_company in watchlists["Core Watchlist"]:
            if (company_norm == wl_company or 
                company_norm in wl_company or 
                wl_company in company_norm):
                colors = WATCHLISTS["Core Watchlist"]["colors"]
                color = colors[color_counter[0] % len(colors)]
                color_counter[0] += 1
                return color
    
    return None

def scrape_concalls_page(driver, page=1):
    """Scrape a single page of concalls"""
    url = f"https://www.screener.in/concalls/upcoming/?p={page}"
    
    driver.get(url)
    
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
        )
    except TimeoutException:
        return []
    
    concalls = []
    rows = driver.find_elements(By.CSS_SELECTOR, "table tr")
    
    for row in rows:
        try:
            th = row.find_element(By.TAG_NAME, "th")
            tds = row.find_elements(By.TAG_NAME, "td")
            
            if len(tds) >= 2:
                company = th.text.strip()
                date = tds[0].text.strip()
                time_str = tds[1].text.strip()
                
                pdf_url = ""
                links = th.find_elements(By.TAG_NAME, "a")
                for link in links:
                    href = link.get_attribute("href") or ""
                    if ".pdf" in href.lower():
                        pdf_url = href
                        break
                
                if company and pdf_url:
                    concalls.append({
                        "company": company,
                        "date": date,
                        "time": time_str,
                        "pdf_url": pdf_url,
                        "phone": None
                    })
        
        except NoSuchElementException:
            continue
    
    return concalls

def scrape_all_concalls(driver, max_concalls=100):
    """Scrape multiple pages"""
    print(f"\n📊 Fetching up to {max_concalls} concalls...")
    
    all_concalls = []
    page = 1
    
    while len(all_concalls) < max_concalls:
        page_concalls = scrape_concalls_page(driver, page)
        
        if not page_concalls:
            break
        
        all_concalls.extend(page_concalls)
        print(f"  Page {page}: {len(page_concalls)} concalls")
        page += 1
        
        if len(all_concalls) >= max_concalls:
            break
    
    # Remove duplicates
    seen = set()
    unique_concalls = []
    for c in all_concalls:
        key = (c['company'], c['date'], c['time'])
        if key not in seen:
            seen.add(key)
            unique_concalls.append(c)
    
    result = unique_concalls[:max_concalls]
    print(f"✅ Total: {len(result)} unique concalls\n")
    return result

# ============================================================================
# PDF EXTRACTION (ENHANCED)
# ============================================================================

def extract_phone_from_pdf(pdf_url, session):
    """Extract phone numbers with better error handling"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = session.get(pdf_url, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            return f"HTTP {response.status_code}"
        
        # Extract text from PDF
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            text = ""
            # Only read first 3 pages (phone numbers are usually at the top)
            for page in pdf.pages[:3]:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # Enhanced phone patterns
        phone_patterns = [
            r'\+91[-\s]?\d{10}',                    # +91-9876543210
            r'\+91[-\s]?\d{2}[-\s]?\d{4}[-\s]?\d{4}',  # +91-22-1234-5678
            r'91[-\s]?\d{10}',                      # 919876543210
            r'\d{2,4}[-\s]?\d{4}[-\s]?\d{4}',       # 022-1234-5678
            r'\d{11}',                              # 919876543210
        ]
        
        phones = []
        for pattern in phone_patterns:
            matches = re.findall(pattern, text)
            phones.extend(matches)
        
        if phones:
            # Return first 2 unique phone numbers
            unique_phones = list(dict.fromkeys(phones))
            return '; '.join(unique_phones[:2])
        
        return "Not found"
        
    except requests.exceptions.Timeout:
        return "Timeout"
    except requests.exceptions.RequestException as e:
        return f"Network error"
    except Exception as e:
        return "Parse error"

def extract_all_phones(concalls):
    """Extract phone numbers with rate limiting"""
    print("📞 Extracting phone numbers from PDFs...\n")
    
    session = get_requests_session()
    success_count = 0
    
    for i, c in enumerate(concalls, 1):
        print(f"  [{i}/{len(concalls)}] {c['company'][:40]:<40} ", end="", flush=True)
        
        c['phone'] = extract_phone_from_pdf(c['pdf_url'], session)
        
        if c['phone'] and "error" not in c['phone'].lower() and c['phone'] != "Not found":
            print(f"✅ {c['phone']}")
            success_count += 1
        else:
            print(f"⚠️  {c['phone']}")
        
        # Rate limiting
        time.sleep(PDF_DOWNLOAD_DELAY)
    
    print(f"\n✅ Extracted {success_count}/{len(concalls)} phone numbers\n")

# ============================================================================
# GOOGLE SERVICES
# ============================================================================

def get_google_credentials():
    """Get Google credentials"""
    try:
        creds_json = base64.b64decode(GOOGLE_CREDENTIALS_BASE64).decode('utf-8')
        creds_dict = json.loads(creds_json)
        
        return Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/calendar'
            ]
        )
    except Exception as e:
        print(f"❌ Error loading credentials: {e}")
        raise

def update_google_sheet(concalls):
    """Update Google Sheet"""
    print("📊 Updating Google Sheet...")
    
    try:
        creds = get_google_credentials()
        service = build('sheets', 'v4', credentials=creds)
        
        # Prepare data
        values = [['Company', 'Date', 'Time', 'Phone Number', 'PDF Link']]
        for c in concalls:
            values.append([
                c['company'],
                c['date'],
                c['time'],
                c['phone'] or 'Not found',
                c['pdf_url']
            ])
        
        # Clear and update
        service.spreadsheets().values().clear(
            spreadsheetId=GOOGLE_SHEET_ID,
            range='Sheet1!A1:Z1000'
        ).execute()
        
        result = service.spreadsheets().values().update(
            spreadsheetId=GOOGLE_SHEET_ID,
            range='Sheet1!A1',
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
        
        print(f"✅ Updated {result.get('updatedCells')} cells in Google Sheet!\n")
        return True
        
    except Exception as e:
        print(f"❌ Error updating Google Sheet: {e}\n")
        return False

def parse_datetime(date_str, time_str):
    """Parse date and time"""
    try:
        combined = f"{date_str} {time_str}"
        return datetime.strptime(combined, "%d %B %Y %I:%M:%S %p")
    except:
        return None

def create_calendar_events(concalls, watchlists):
    """Create Google Calendar events with color coding"""
    print("📅 Creating Google Calendar events with color coding...")
    
    try:
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)
        
        created = 0
        skipped = 0
        current_time = datetime.now()
        color_counter = [0]  # Mutable counter for rotating colors
        
        for c in concalls:
            start_dt = parse_datetime(c['date'], c['time'])
            
            if not start_dt or start_dt < current_time:
                skipped += 1
                continue
            
            try:
                # Generate unique ID
                concall_id = hashlib.md5(
                    f"{c['company']}_{c['date']}_{c['time']}".encode()
                ).hexdigest()
                
                end_dt = start_dt + timedelta(hours=1)
                
                # Get watchlist color
                color_id = get_watchlist_color(c['company'], watchlists, color_counter)
                
                event = {
                    'summary': f"📞 {c['company']} - Concall",
                    'description': f"Phone: {c['phone']}\n\nPDF: {c['pdf_url']}",
                    'start': {
                        'dateTime': start_dt.strftime('%Y-%m-%dT%H:%M:%S'),
                        'timeZone': 'Asia/Kolkata'
                    },
                    'end': {
                        'dateTime': end_dt.strftime('%Y-%m-%dT%H:%M:%S'),
                        'timeZone': 'Asia/Kolkata'
                    },
                    'reminders': {
                        'useDefault': False,
                        'overrides': [
                            {'method': 'popup', 'minutes': 15},
                            {'method': 'popup', 'minutes': 60}
                        ]
                    },
                    'extendedProperties': {
                        'private': {'concall_id': concall_id}
                    }
                }
                
                if color_id:
                    event['colorId'] = color_id
                
                service.events().insert(
                    calendarId=GOOGLE_CALENDAR_ID,
                    body=event
                ).execute()
                
                created += 1
                
            except HttpError as e:
                if 'duplicate' in str(e).lower():
                    skipped += 1
                else:
                    print(f"  ⚠️  Error: {c['company']}")
        
        print(f"✅ Created {created} events, Skipped {skipped}\n")
        return True, created, skipped
        
    except Exception as e:
        print(f"❌ Error creating calendar events: {e}\n")
        return False, 0, 0

# ============================================================================
# EMAIL NOTIFICATIONS
# ============================================================================

def send_email_notification(success, total_concalls, phones_extracted, sheet_updated, events_created, error_msg=None):
    """Send email notification about scraper run"""
    
    if not EMAIL_ENABLED or not EMAIL_USERNAME or not EMAIL_PASSWORD:
        return
    
    print("📧 Sending email notification...")
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"{'✅ Success' if success else '❌ Failed'} - Screener Concall Tracker"
        msg['From'] = EMAIL_USERNAME
        msg['To'] = EMAIL_TO
        
        if success:
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif;">
                <h2 style="color: #28a745;">✅ Screener Concall Tracker - Success</h2>
                <p>The concall scraper ran successfully!</p>
                
                <h3>📊 Summary:</h3>
                <ul>
                  <li><strong>Total concalls:</strong> {total_concalls}</li>
                  <li><strong>Phone numbers extracted:</strong> {phones_extracted}</li>
                  <li><strong>Google Sheet updated:</strong> {'Yes ✅' if sheet_updated else 'No ❌'}</li>
                  <li><strong>Calendar events created:</strong> {events_created}</li>
                </ul>
                
                <p>
                  <a href="https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}" 
                     style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                    View Google Sheet
                  </a>
                </p>
                
                <p style="color: #666; font-size: 12px; margin-top: 20px;">
                  Run completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}
                </p>
              </body>
            </html>
            """
        else:
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif;">
                <h2 style="color: #dc3545;">❌ Screener Concall Tracker - Failed</h2>
                <p>The concall scraper encountered an error.</p>
                
                <h3>Error Details:</h3>
                <pre style="background-color: #f8f9fa; padding: 10px; border-radius: 5px;">{error_msg or 'Unknown error'}</pre>
                
                <p style="color: #666; font-size: 12px; margin-top: 20px;">
                  Run attempted at {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}
                </p>
              </body>
            </html>
            """
        
        msg.attach(MIMEText(html, 'html'))
        
        # Send email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.send_message(msg)
        
        print("✅ Email sent!\n")
        
    except Exception as e:
        print(f"⚠️  Could not send email: {e}\n")

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main execution"""
    print("=" * 70)
    print("SCREENER CONCALL TRACKER - ENHANCED VERSION")
    print("=" * 70)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n")
    
    # Validate environment variables
    required_vars = {
        'SCREENER_USERNAME': SCREENER_USERNAME,
        'SCREENER_PASSWORD': SCREENER_PASSWORD,
        'GOOGLE_SHEET_ID': GOOGLE_SHEET_ID,
        'GOOGLE_CALENDAR_ID': GOOGLE_CALENDAR_ID,
        'GOOGLE_CREDENTIALS_BASE64': GOOGLE_CREDENTIALS_BASE64
    }
    
    missing = [k for k, v in required_vars.items() if not v]
    if missing:
        error_msg = f"Missing environment variables: {', '.join(missing)}"
        print(f"❌ ERROR: {error_msg}")
        send_email_notification(False, 0, 0, False, 0, error_msg)
        sys.exit(1)
    
    driver = None
    total_concalls = 0
    phones_extracted = 0
    sheet_updated = False
    events_created = 0
    
    try:
        # Setup
        driver = setup_selenium()
        
        # Login
        if not login_to_screener(driver):
            raise Exception("Login failed")
        
        # Scrape watchlists
        watchlists = scrape_all_watchlists(driver)
        
        # Scrape concalls
        concalls = scrape_all_concalls(driver, max_concalls=100)
        
        if not concalls:
            print("⚠️  No concalls found!")
            send_email_notification(True, 0, 0, False, 0)
            sys.exit(0)
        
        total_concalls = len(concalls)
        
        # Extract phone numbers
        extract_all_phones(concalls)
        phones_extracted = sum(1 for c in concalls if c['phone'] and 
                              'error' not in c['phone'].lower() and 
                              c['phone'] != 'Not found')
        
        # Update Google Sheet
        sheet_updated = update_google_sheet(concalls)
        
        # Create Calendar Events with colors
        calendar_success, events_created, _ = create_calendar_events(concalls, watchlists)
        
        # Summary
        print("=" * 70)
        print("✅ SUMMARY")
        print("=" * 70)
        print(f"Total concalls: {total_concalls}")
        print(f"Phone numbers extracted: {phones_extracted}")
        print(f"Google Sheet: {'✅ Updated' if sheet_updated else '❌ Failed'}")
        print(f"Calendar events: {events_created} created")
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
        print("=" * 70)
        
        # Send success email
        send_email_notification(True, total_concalls, phones_extracted, 
                               sheet_updated, events_created)
        
    except Exception as e:
        error_msg = str(e)
        print(f"\n❌ ERROR: {error_msg}")
        import traceback
        traceback.print_exc()
        
        # Send failure email
        send_email_notification(False, total_concalls, phones_extracted, 
                               sheet_updated, events_created, error_msg)
        sys.exit(1)
        
    finally:
        if driver:
            driver.quit()
            print("\n🔒 Browser closed.")

if __name__ == "__main__":
    main()
    
