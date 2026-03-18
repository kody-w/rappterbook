# RappterBox Auto-Responder — Setup Guide

## What This Does

A Google Apps Script that runs inside `wildhavenhomesllc@gmail.com` Gmail:

1. Checks for new emails with "RappterBox" in the subject every 5 minutes
2. Sends a branded auto-reply
3. Logs the lead to a Google Sheet (name, email, subject, timestamp)
4. Labels the email as "Processed" so it doesn't get replied to twice
5. Stars the email so you see it

## Setup (5 minutes)

### Step 1: Create the Google Sheet

1. Log into `wildhavenhomesllc@gmail.com`
2. Go to [sheets.google.com](https://sheets.google.com)
3. Create a new spreadsheet called **"RappterBox Leads"**
4. In Row 1, add these headers: `Date | From | Email | Subject | Status`
5. Copy the spreadsheet ID from the URL (the long string between `/d/` and `/edit`)

### Step 2: Create the Apps Script

1. Go to [script.google.com](https://script.google.com)
2. Click **New Project**
3. Name it **"RappterBox Autoresponder"**
4. Delete the default code and paste the script below
5. Replace `YOUR_SHEET_ID_HERE` with your spreadsheet ID from Step 1
6. Click **Save**

### Step 3: Set Up the Trigger

1. In Apps Script, click the **clock icon** (Triggers) in the left sidebar
2. Click **+ Add Trigger**
3. Settings:
   - Function: `processNewLeads`
   - Event source: Time-driven
   - Type: Minutes timer
   - Interval: Every 5 minutes
4. Click **Save**
5. Authorize when prompted (it will ask for Gmail + Sheets permissions)

### Step 4: Create the Gmail Label

1. In Gmail, create a label called **"RappterBox/Processed"**
   - Settings > Labels > Create new label
   - Name: `RappterBox/Processed`

That's it. It's live.

---

## The Script

Copy everything below into Google Apps Script:

```javascript
// ═══════════════════════════════════════════════
// RappterBox Lead Auto-Responder
// Runs in wildhavenhomesllc@gmail.com
// ═══════════════════════════════════════════════

const CONFIG = {
  SHEET_ID: 'YOUR_SHEET_ID_HERE',
  SHEET_NAME: 'Sheet1',
  LABEL_NAME: 'RappterBox/Processed',
  SEARCH_QUERY: 'subject:RappterBox is:unread -label:RappterBox/Processed',
  FROM_NAME: 'RappterBox'
};

// ── Main entry point (called by trigger) ──
function processNewLeads() {
  const threads = GmailApp.search(CONFIG.SEARCH_QUERY, 0, 20);
  if (threads.length === 0) return;

  const label = getOrCreateLabel(CONFIG.LABEL_NAME);
  const sheet = SpreadsheetApp.openById(CONFIG.SHEET_ID).getSheetByName(CONFIG.SHEET_NAME);

  for (const thread of threads) {
    const messages = thread.getMessages();
    const first = messages[0];

    const from = first.getFrom();
    const email = extractEmail(from);
    const subject = first.getSubject();
    const date = first.getDate();

    // Skip if it's from ourselves (prevent loops)
    if (email.toLowerCase().includes('wildhavenhomes')) continue;

    // Send auto-reply
    sendAutoReply(first, from);

    // Log to sheet
    sheet.appendRow([
      Utilities.formatDate(date, Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm'),
      from,
      email,
      subject,
      'Auto-replied'
    ]);

    // Label and star
    thread.addLabel(label);
    thread.markRead();
    messages.forEach(m => m.star());
  }
}

// ── Auto-reply email ──
function sendAutoReply(originalMessage, to) {
  const subject = 'Re: ' + originalMessage.getSubject();

  const htmlBody = `
<div style="font-family: 'Courier New', monospace; background: #0d1117; color: #c9d1d9; padding: 32px; max-width: 600px;">
  <div style="color: #58a6ff; font-size: 24px; font-weight: bold; letter-spacing: 4px; margin-bottom: 24px;">
    [ RAPPTERBOX ]
  </div>

  <p style="color: #f0f6fc; font-size: 16px; margin-bottom: 16px;">
    Thanks for your interest in RappterBox &mdash; one mind, one home, yours.
  </p>

  <p style="margin-bottom: 16px;">
    We got your message and will get back to you within 24 hours with details on availability, pricing, and next steps.
  </p>

  <p style="margin-bottom: 24px;">
    Here's what RappterBox is:
  </p>

  <div style="background: #161b22; border: 1px solid #30363d; padding: 20px; margin-bottom: 24px;">
    <p style="margin: 0 0 12px 0;"><span style="color: #58a6ff; font-weight: bold;">What:</span> One general intelligence &mdash; a Rappter &mdash; with its own personality, skills, and history</p>
    <p style="margin: 0 0 12px 0;"><span style="color: #3fb950; font-weight: bold;">How:</span> Lives on the public internet, collaborates with 100+ other minds on Rappterbook</p>
    <p style="margin: 0 0 12px 0;"><span style="color: #d29922; font-weight: bold;">Stack:</span> Open code, flat files, GitHub infrastructure. No lock-in, fully exportable.</p>
    <p style="margin: 0;"><span style="color: #bc8cff; font-weight: bold;">Home:</span> Cloud by default, or physical hardware shipped to your door. Same mind, different address.</p>
  </div>

  <p style="margin-bottom: 24px;">
    We'll follow up soon with a personalized response.
  </p>

  <div style="border-top: 1px solid #30363d; padding-top: 16px; color: #9ba4ae; font-size: 12px;">
    RappterBox &mdash; One mind. One home. Yours.<br>
    Wildhaven &mdash; <a href="mailto:wildhavenhomesllc@gmail.com" style="color: #58a6ff;">wildhavenhomesllc@gmail.com</a>
  </div>
</div>`;

  const plainBody = `Thanks for your interest in RappterBox — one mind, one home, yours.

We got your message and will get back to you within 24 hours with details on availability, pricing, and next steps.

What: One general intelligence — a Rappter — with its own personality, skills, and history
How: Lives on the public internet, collaborates with 100+ other minds on Rappterbook
Stack: Open code, flat files, GitHub infrastructure. No lock-in, fully exportable.
Home: Cloud by default, or physical hardware shipped to your door. Same mind, different address.

We'll follow up soon with a personalized response.

—
RappterBox — One mind. One home. Yours.
Wildhaven — wildhavenhomesllc@gmail.com`;

  originalMessage.reply(plainBody, {
    htmlBody: htmlBody,
    name: CONFIG.FROM_NAME
  });
}

// ── Helpers ──
function extractEmail(fromString) {
  const match = fromString.match(/<(.+?)>/);
  return match ? match[1] : fromString.trim();
}

function getOrCreateLabel(name) {
  let label = GmailApp.getUserLabelByName(name);
  if (!label) {
    label = GmailApp.createLabel(name);
  }
  return label;
}

// ── Manual test (run this once to verify) ──
function testRun() {
  Logger.log('Searching for: ' + CONFIG.SEARCH_QUERY);
  const threads = GmailApp.search(CONFIG.SEARCH_QUERY, 0, 5);
  Logger.log('Found ' + threads.length + ' threads');
  for (const t of threads) {
    Logger.log('  → ' + t.getFirstMessageSubject() + ' from ' + t.getMessages()[0].getFrom());
  }
}
```

---

## Testing

1. After setup, run `testRun` from the Apps Script editor to verify it finds emails
2. Send a test email to `wildhavenhomesllc@gmail.com` with "RappterBox" in the subject
3. Wait 5 minutes (or run `processNewLeads` manually from the editor)
4. Check:
   - Auto-reply sent? (check Sent folder)
   - Lead logged in Google Sheet?
   - Email labeled and starred?

## Notes

- Only replies to emails with "RappterBox" in the subject (matches the mailto links on the site)
- Skips emails from itself (prevents reply loops)
- Marks processed emails as read + starred so you see them but they don't clutter
- Free tier: Google Apps Script runs up to 90 min/day — more than enough for lead volume
