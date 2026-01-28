# 📞 Screener Concall Tracker

Automated system that tracks upcoming investor conference calls from Screener.in, extracts dial-in numbers from PDFs, and syncs everything to Google Sheets + Calendar.

**Zero manual work. Runs daily at 7 AM IST.**

## ✨ Features

* 🔍 Scrapes 100 upcoming concalls from Screener.in
* 📄 Extracts phone numbers from PDF announcements
* 📊 Auto-updates Google Sheet with all concall details
* 📅 Creates Google Calendar events with reminders
* ☁️ Runs automatically via GitHub Actions (even if your laptop is off)

## 📊 Your Live Data

* **Google Sheet:** https://docs.google.com/spreadsheets/d/1GDG2ICQvoroKBjVgGdnWjUpxir6lvYxDO14afFg_oiY
* **Google Calendar:** Check your "Concall Tracker" calendar

## ⚙️ How It Works

```
Every day at 7 AM IST:
┌─────────────────┐
│  Screener.in    │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Scrape 100     │
│  Concalls       │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Download PDFs  │
│  Extract Phones │
└────────┬────────┘
         ▼
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌──────────┐
│ Sheet │ │ Calendar │
└───────┘ └──────────┘
```

## 🛠️ Tech Stack

* Python + Selenium (web scraping)
* pdfplumber (PDF extraction)
* Google Sheets API
* Google Calendar API
* GitHub Actions (automation)

## 🚀 Setup Complete!

All configuration is done via GitHub Secrets. The scraper will run automatically every day at 7 AM IST.

### Manual Trigger

To run the scraper manually:
1. Go to the "Actions" tab in your GitHub repository
2. Click on "Daily Concall Scraper"
3. Click "Run workflow"
4. Wait 2-3 minutes for it to complete

## 📝 Secrets Required

The following secrets are configured in your GitHub repository:
- `SCREENER_USERNAME` - Your Screener.in email
- `SCREENER_PASSWORD` - Your Screener.in password
- `GOOGLE_SHEET_ID` - Google Sheet ID
- `GOOGLE_CALENDAR_ID` - Google Calendar ID
- `GOOGLE_CREDENTIALS_BASE64` - Base64-encoded service account JSON

## 🔧 Troubleshooting

If the scraper fails:
1. Check the "Actions" tab for error logs
2. Verify all secrets are correctly set
3. Ensure the service account has access to your Sheet and Calendar

## 📄 License

MIT

---

*Built with Claude Code* 🤖
