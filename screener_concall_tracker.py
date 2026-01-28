#!/usr/bin/env python3
"""
Screener.in Concall Tracker
Automated scraper that tracks upcoming investor concalls from Screener.in
"""

import os
import sys
import time
import re
import base64
import json
from datetime import datetime, timedelta
from io import BytesIO

# Third-party imports
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

# Configuration from environment variables
SCREENER_USERNAME = os.getenv('SCREENER_USERNAME')
SCREENER_PASSWORD = os.getenv('SCREENER_PASSWORD')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID')
GOOGLE_CREDENTIALS_BASE64 = os.getenv('GOOGLE_CREDENTIALS_BASE64')


def setup_selenium():
    """Configure Selenium WebDriver with Chrome in headless mode"""
    print("Setting up Selenium WebDriver...")
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver


def login_to_screener(driver):
    """Login to Screener.in"""
    print("Logging into Screener.in...")
    try:
        driver.get('https://www.screener.in/login/')
        
        # Wait for login form
        wait = WebDriverWait(driver, 10)
        username_field = wait.until(EC.presence_of_element_located((By.NAME, 'username')))
        
        # Enter credentials
        username_field.send_keys(SCREENER_USERNAME)
        driver.find_element(By.NAME, 'password').send_keys(SCREENER_PASSWORD)
        
        # Submit login
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        
        # Wait for redirect after login
        time.sleep(3)
        print("Login successful!")
        return True
        
    except Exception as e:
        print(f"Login failed: {e}")
        return False


def scrape_concalls(driver, max_concalls=100):
    """Scrape upcoming concalls from Screener.in"""
    print(f"Scraping up to {max_concalls} concalls...")
    
    try:
        # Navigate to the CORRECT concalls page
        driver.get('https://www.screener.in/concalls/upcoming/')
        time.sleep(5)  # Give more time for page to load
        
        concalls = []
        
        # Try multiple possible selectors
        print("Looking for concall listings...")
        
        # Try to find the table or card elements
        try:
            # First try: look for table rows
            rows = driver.find_elements(By.CSS_SELECTOR, 'table tbody tr')
            if rows:
                print(f"Found {len(rows)} rows in table")
            
            # If no table rows, try card-based layout
            if not rows:
                rows = driver.find_elements(By.CSS_SELECTOR, '.concall-card, .card, article')
                if rows:
                    print(f"Found {len(rows)} cards")
            
            # If still nothing, try any links to company pages
            if not rows:
                rows = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/company/"]')
                if rows:
                    print(f"Found {len(rows)} company links")
            
            if not rows:
                print("ERROR: Could not find any concall elements on the page")
                print("Page source preview:")
                print(driver.page_source[:1000])  # Print first 1000 chars for debugging
                return []
            
        except Exception as e:
            print(f"Error finding elements: {e}")
            return []
        
        # Parse each row/card
        for idx, row in enumerate(rows[:max_concalls]):
            try:
                # Debug: print what we see in first few rows
                if idx < 3:
                    print(f"\nDEBUG Row {idx}: {row.text[:200]}")
                
                # Try to extract data - this depends on the actual page structure
                try:
                    # Method 1: Table-based layout
                    cells = row.find_elements(By.TAG_NAME, 'td')
                    
                    # Debug first row
                    if idx == 0:
                        print(f"DEBUG: Found {len(cells)} cells in first row")
                        for i, cell in enumerate(cells[:5]):
                            print(f"  Cell {i}: {cell.text[:100]}")
                    
                    if len(cells) >= 3:
                        company_elem = cells[0].find_element(By.TAG_NAME, 'a')
                        company_name = company_elem.text.strip()
                        company_url = company_elem.get_attribute('href')
                        date_text = cells[1].text.strip()
                        time_text = cells[2].text.strip() if len(cells) > 2 else ""
                        
                        # Try to find PDF link
                        pdf_link = None
                        try:
                            pdf_elem = cells[3].find_element(By.TAG_NAME, 'a') if len(cells) > 3 else None
                            if pdf_elem:
                                pdf_link = pdf_elem.get_attribute('href')
                        except:
                            pass
                        
                        concall_data = {
                            'company': company_name,
                            'company_url': company_url,
                            'date': date_text,
                            'time': time_text,
                            'pdf_link': pdf_link,
                            'phone': None
                        }
                        concalls.append(concall_data)
                        print(f"  {idx+1}. {company_name} - {date_text} {time_text}")
                        continue
                        
                except:
                    # Method 2: Card or link-based layout
                    text = row.text.strip()
                    if text:
                        # Try to extract company name from link
                        try:
                            company_link = row.find_element(By.CSS_SELECTOR, 'a[href*="/company/"]')
                            company_name = company_link.text.strip()
                            company_url = company_link.get_attribute('href')
                        except:
                            company_name = text.split('\n')[0] if '\n' in text else text[:50]
                            company_url = row.get_attribute('href') if row.tag_name == 'a' else ""
                        
                        # Try to extract date/time from text
                        date_match = re.search(r'\d{1,2}\s+\w+\s+\d{4}', text)
                        time_match = re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)', text)
                        
                        date_text = date_match.group(0) if date_match else ""
                        time_text = time_match.group(0) if time_match else ""
                        
                        # Try to find PDF link
                        pdf_link = None
                        try:
                            pdf_elem = row.find_element(By.CSS_SELECTOR, 'a[href*=".pdf"]')
                            pdf_link = pdf_elem.get_attribute('href')
                        except:
                            pass
                        
                        if company_name:
                            concall_data = {
                                'company': company_name,
                                'company_url': company_url,
                                'date': date_text,
                                'time': time_text,
                                'pdf_link': pdf_link,
                                'phone': None
                            }
                            concalls.append(concall_data)
                            print(f"  {idx+1}. {company_name} - {date_text} {time_text}")
                
            except Exception as e:
                print(f"  Error parsing row {idx+1}: {e}")
                continue
        
        print(f"Successfully scraped {len(concalls)} concalls!")
        return concalls
        
    except Exception as e:
        print(f"Error scraping concalls: {e}")
        import traceback
        traceback.print_exc()
        return []


def extract_phone_from_pdf(pdf_url):
    """Extract phone numbers from PDF announcement"""
    if not pdf_url:
        return None
    
    try:
        print(f"  Downloading PDF: {pdf_url}")
        response = requests.get(pdf_url, timeout=10)
        
        if response.status_code != 200:
            return None
        
        # Extract text from PDF
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # Search for Indian phone numbers
        phone_patterns = [
            r'\+91[\s-]?\d{10}',
            r'\d{3}[\s-]?\d{3}[\s-]?\d{4}',
            r'\d{4}[\s-]?\d{3}[\s-]?\d{3}',
        ]
        
        for pattern in phone_patterns:
            matches = re.findall(pattern, text)
            if matches:
                phone = matches[0].strip()
                print(f"  Found phone: {phone}")
                return phone
        
        print(f"  No phone number found in PDF")
        return None
        
    except Exception as e:
        print(f"  Error extracting phone from PDF: {e}")
        return None


def process_concalls_with_phones(concalls):
    """Process concalls and extract phone numbers from PDFs"""
    print("\nExtracting phone numbers from PDFs...")
    
    success_count = 0
    for idx, concall in enumerate(concalls):
        if concall['pdf_link']:
            phone = extract_phone_from_pdf(concall['pdf_link'])
            concall['phone'] = phone
            if phone:
                success_count += 1
        
        # Rate limiting
        if idx % 10 == 0 and idx > 0:
            print(f"  Processed {idx}/{len(concalls)} PDFs...")
            time.sleep(1)
    
    print(f"Successfully extracted phone numbers from {success_count}/{len(concalls)} PDFs")
    return concalls


def get_google_credentials():
    """Decode and return Google service account credentials"""
    try:
        credentials_json = base64.b64decode(GOOGLE_CREDENTIALS_BASE64).decode('utf-8')
        credentials_dict = json.loads(credentials_json)
        
        creds = Credentials.from_service_account_info(
            credentials_dict,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/calendar'
            ]
        )
        return creds
    except Exception as e:
        print(f"Error loading Google credentials: {e}")
        raise


def update_google_sheet(concalls):
    """Update Google Sheet with concall data"""
    print("\nUpdating Google Sheet...")
    
    try:
        creds = get_google_credentials()
        service = build('sheets', 'v4', credentials=creds)
        
        # Prepare data with headers
        values = [['Company', 'Date', 'Time', 'Phone Number', 'PDF Link', 'Company URL', 'Last Updated']]
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')
        
        for concall in concalls:
            values.append([
                concall['company'],
                concall['date'],
                concall['time'],
                concall['phone'] or 'Not found',
                concall['pdf_link'] or 'N/A',
                concall['company_url'] or 'N/A',
                timestamp
            ])
        
        # Clear existing data and write new data
        body = {'values': values}
        
        # Clear the sheet first
        service.spreadsheets().values().clear(
            spreadsheetId=GOOGLE_SHEET_ID,
            range='Sheet1!A1:Z1000'
        ).execute()
        
        # Write new data
        result = service.spreadsheets().values().update(
            spreadsheetId=GOOGLE_SHEET_ID,
            range='Sheet1!A1',
            valueInputOption='RAW',
            body=body
        ).execute()
        
        print(f"Successfully updated {result.get('updatedCells')} cells in Google Sheet!")
        return True
        
    except HttpError as e:
        print(f"Google Sheets API error: {e}")
        return False
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        import traceback
        traceback.print_exc()
        return False


def parse_concall_datetime(date_str, time_str):
    """Parse concall date and time into datetime object"""
    try:
        datetime_str = f"{date_str} {time_str}"
        dt = datetime.strptime(datetime_str, "%d %b %Y %I:%M %p")
        return dt
    except Exception as e:
        print(f"  Error parsing datetime '{date_str} {time_str}': {e}")
        # Try alternative formats
        try:
            dt = datetime.strptime(datetime_str, "%d %B %Y %I:%M %p")
            return dt
        except:
            return None


def create_calendar_events(concalls):
    """Create Google Calendar events for concalls"""
    print("\nCreating Google Calendar events...")
    
    try:
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)
        
        created_count = 0
        
        for concall in concalls:
            try:
                # Parse datetime
                dt = parse_concall_datetime(concall['date'], concall['time'])
                if not dt:
                    print(f"  Skipping {concall['company']} - invalid date/time")
                    continue
                
                # Create event
                event = {
                    'summary': f"{concall['company']} Concall",
                    'description': f"Company: {concall['company']}\n"
                                 f"Phone: {concall['phone'] or 'Check PDF'}\n"
                                 f"PDF: {concall['pdf_link'] or 'N/A'}\n"
                                 f"Company URL: {concall['company_url']}",
                    'start': {
                        'dateTime': dt.isoformat(),
                        'timeZone': 'Asia/Kolkata'
                    },
                    'end': {
                        'dateTime': (dt + timedelta(hours=1)).isoformat(),
                        'timeZone': 'Asia/Kolkata'
                    },
                    'reminders': {
                        'useDefault': False,
                        'overrides': [
                            {'method': 'popup', 'minutes': 30},
                            {'method': 'popup', 'minutes': 10}
                        ]
                    }
                }
                
                # Create event
                event = service.events().insert(
                    calendarId=GOOGLE_CALENDAR_ID,
                    body=event
                ).execute()
                
                created_count += 1
                
            except Exception as e:
                print(f"  Error creating event for {concall['company']}: {e}")
                continue
        
        print(f"Successfully created {created_count} calendar events!")
        return True
        
    except HttpError as e:
        print(f"Google Calendar API error: {e}")
        return False
    except Exception as e:
        print(f"Error creating calendar events: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main execution function"""
    print("=" * 60)
    print("SCREENER CONCALL TRACKER")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n")
    
    # Validate environment variables
    required_vars = [
        'SCREENER_USERNAME',
        'SCREENER_PASSWORD',
        'GOOGLE_SHEET_ID',
        'GOOGLE_CALENDAR_ID',
        'GOOGLE_CREDENTIALS_BASE64'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print(f"ERROR: Missing environment variables: {', '.join(missing_vars)}")
        sys.exit(1)
    
    driver = None
    
    try:
        # Step 1: Setup Selenium
        driver = setup_selenium()
        
        # Step 2: Login to Screener
        if not login_to_screener(driver):
            raise Exception("Failed to login to Screener.in")
        
        # Step 3: Scrape concalls
        concalls = scrape_concalls(driver, max_concalls=100)
        if not concalls:
            print("No concalls found!")
            sys.exit(0)
        
        # Step 4: Extract phone numbers from PDFs (optional - comment out if too slow)
        # concalls = process_concalls_with_phones(concalls)
        
        # Step 5: Update Google Sheet
        sheet_success = update_google_sheet(concalls)
        
        # Step 6: Create Calendar Events
        calendar_success = create_calendar_events(concalls)
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total concalls scraped: {len(concalls)}")
        print(f"Phone numbers extracted: {sum(1 for c in concalls if c['phone'])}")
        print(f"Google Sheet updated: {'✓' if sheet_success else '✗'}")
        print(f"Calendar events created: {'✓' if calendar_success else '✗'}")
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
