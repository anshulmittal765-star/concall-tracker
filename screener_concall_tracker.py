#!/usr/bin/env python3
"""
Screener.in Concall Tracker - Based on working reference
"""

import os
import sys
import time
import re
import base64
import json
from datetime import datetime, timedelta
from io import BytesIO

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import requests
import pdfplumber
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Configuration
SCREENER_USERNAME = os.getenv('SCREENER_USERNAME')
SCREENER_PASSWORD = os.getenv('SCREENER_PASSWORD')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID')
GOOGLE_CREDENTIALS_BASE64 = os.getenv('GOOGLE_CREDENTIALS_BASE64')

def setup_selenium():
    """Configure Selenium WebDriver"""
    print("Setting up Selenium WebDriver...")
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    
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
            print("Login failed!")
            return False
        
        print("Login successful!")
        return True
        
    except Exception as e:
        print(f"Login failed: {e}")
        return False

def scrape_concalls_page(driver, page=1):
    """Scrape a single page of concalls - CORRECT METHOD based on working code"""
    url = f"https://www.screener.in/concalls/upcoming/?p={page}"
    print(f"\nScraping page {page}: {url}")
    
    driver.get(url)
    
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
        )
    except TimeoutException:
        print(f"Page {page} did not load in time")
        return []
    
    concalls = []
    # KEY DIFFERENCE: Look for ALL table rows (including those with th tags)
    rows = driver.find_elements(By.CSS_SELECTOR, "table tr")
    
    print(f"Found {len(rows)} total rows")
    
    for idx, row in enumerate(rows):
        try:
            # KEY DIFFERENCE: Company name is in <th>, not <td>!
            th = row.find_element(By.TAG_NAME, "th")
            tds = row.find_elements(By.TAG_NAME, "td")
            
            if len(tds) >= 2:
                # Extract data
                company = th.text.strip()
                date = tds[0].text.strip()
                time_str = tds[1].text.strip()
                
                # Find PDF link inside the th element
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
                    
                    if idx < 5:  # Print first 5
                        print(f"  ✓ {company} - {date} {time_str}")
        
        except NoSuchElementException:
            continue
    
    print(f"Extracted {len(concalls)} concalls from page {page}")
    return concalls

def scrape_all_concalls(driver, max_concalls=100):
    """Scrape multiple pages to get concalls"""
    print(f"\nFetching up to {max_concalls} concalls...")
    
    all_concalls = []
    page = 1
    
    while len(all_concalls) < max_concalls:
        page_concalls = scrape_concalls_page(driver, page)
        
        if not page_concalls:
            print("No more concalls found")
            break
        
        all_concalls.extend(page_concalls)
        page += 1
        
        # Stop if we got enough
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
    print(f"\nTotal: {len(result)} unique concalls")
    return result

def extract_phone_from_pdf(pdf_url):
    """Extract phone numbers from PDF"""
    try:
        response = requests.get(pdf_url, timeout=10)
        if response.status_code != 200:
            return "Download failed"
        
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # Phone patterns
        phone_patterns = [
            r'\+91[-\s]?\d{2}[-\s]?\d{4}[-\s]?\d{4}',
            r'\+91[-\s]?\d{10}',
            r'\d{4}[-\s]?\d{3}[-\s]?\d{4}',
        ]
        
        phones = []
        for pattern in phone_patterns:
            matches = re.findall(pattern, text)
            phones.extend(matches)
        
        if phones:
            return phones[0]
        return "Not found"
        
    except Exception as e:
        return f"Error: {str(e)[:30]}"

def extract_all_phones(concalls):
    """Extract phone numbers from all PDFs"""
    print("\nExtracting phone numbers from PDFs...")
    
    for i, c in enumerate(concalls):
        print(f"[{i+1}/{len(concalls)}] {c['company'][:40]}...", end=" ")
        c['phone'] = extract_phone_from_pdf(c['pdf_url'])
        print(c['phone'])
        time.sleep(0.3)  # Rate limiting

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
        print(f"Error loading credentials: {e}")
        raise

def update_google_sheet(concalls):
    """Update Google Sheet"""
    print("\nUpdating Google Sheet...")
    
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
        
        print(f"✓ Updated {result.get('updatedCells')} cells in Google Sheet!")
        return True
        
    except Exception as e:
        print(f"✗ Error updating Google Sheet: {e}")
        return False

def parse_datetime(date_str, time_str):
    """Parse date and time"""
    try:
        combined = f"{date_str} {time_str}"
        return datetime.strptime(combined, "%d %B %Y %I:%M:%S %p")
    except:
        return None

def create_calendar_events(concalls):
    """Create Google Calendar events"""
    print("\nCreating Google Calendar events...")
    
    try:
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)
        
        created = 0
        skipped = 0
        current_time = datetime.now()
        
        for c in concalls:
            start_dt = parse_datetime(c['date'], c['time'])
            
            if not start_dt:
                skipped += 1
                continue
            
            if start_dt < current_time:
                skipped += 1
                continue
            
            end_dt = start_dt + timedelta(hours=1)
            
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
                }
            }
            
            try:
                service.events().insert(
                    calendarId=GOOGLE_CALENDAR_ID,
                    body=event
                ).execute()
                created += 1
            except HttpError as e:
                if 'duplicate' in str(e).lower():
                    skipped += 1
                else:
                    print(f"  Error: {c['company']}: {e}")
        
        print(f"✓ Created {created} events, Skipped {skipped}")
        return True
        
    except Exception as e:
        print(f"✗ Error creating calendar events: {e}")
        return False

def main():
    """Main execution"""
    print("=" * 60)
    print("SCREENER CONCALL TRACKER")
    print("=" * 60)
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
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)
    
    driver = None
    
    try:
        # Setup
        driver = setup_selenium()
        
        # Login
        if not login_to_screener(driver):
            raise Exception("Login failed")
        
        # Scrape concalls
        concalls = scrape_all_concalls(driver, max_concalls=100)
        
        if not concalls:
            print("No concalls found!")
            sys.exit(0)
        
        # Extract phone numbers (optional - comment out if too slow)
        extract_all_phones(concalls)
        
        # Update Google Sheet
        sheet_success = update_google_sheet(concalls)
        
        # Create Calendar Events
        calendar_success = create_calendar_events(concalls)
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total concalls: {len(concalls)}")
        print(f"Google Sheet: {'✓' if sheet_success else '✗'}")
        print(f"Calendar: {'✓' if calendar_success else '✗'}")
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    finally:
        if driver:
            driver.quit()
            print("\nBrowser closed.")

if __name__ == "__main__":
    main()
