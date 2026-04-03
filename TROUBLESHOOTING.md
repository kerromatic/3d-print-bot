# TROUBLESHOOTING.md - 3D Print Hub Bot

This document captures all issues encountered during development and deployment, along with their fixes.

---

## Issue #1: UnicodeEncodeError - Surrogate Pairs on Windows

**Symptom:** `UnicodeEncodeError: 'utf-8' codec can't encode characters in position 0-1: surrogates not allowed`

**Root Cause:** When pushing Python files through the GitHub web editor (CodeMirror), emoji characters were stored as JavaScript-style surrogate pair escapes (e.g., \\ud83d\\udc4b) instead of actual UTF-8 emoji characters. Windows Python 3.13 cannot encode surrogate pairs to UTF-8.

**Affected Files:** bot/handlers.py, bot/posting.py, bot/scheduler.py, utils/helpers.py

**Fix:** Replace all surrogate pair escapes with actual emoji characters. Use the base64 decode method when pushing files through GitHub's web editor:
```javascript
const b64 = "...base64 encoded UTF-8 content...";
const decoded = atob(b64);
const bytes = new Uint8Array(decoded.length);
for (let i = 0; i < decoded.length; i++) bytes[i] = decoded.charCodeAt(i);
const content = new TextDecoder('utf-8').decode(bytes);
```

**Verification:**
```python
import re
with open('bot/handlers.py', 'r', encoding='utf-8') as f:
    content = f.read()
surrogates = re.findall(r'\\\\ud[89a-f][0-9a-f]{2}', content, re.IGNORECASE)
print(f"Surrogate escapes found: {len(surrogates)}")  # Should be 0
```

---

## Issue #2: GitHub Web Editor - Commit Dialog Not Opening

**Symptom:** Clicking "Commit changes..." does nothing.

**Root Cause:** GitHub requires a detectable diff. If selectAll + insertText produces identical content, no diff is registered.

**Fix:** First delete all content (Cmd+A then Backspace), THEN insert new content. This forces a visible diff and enables the commit dialog.

---

## Issue #3: GitHub Web Editor - Large File Virtualization

**Symptom:** `document.querySelector('.cm-content').innerText` only returns ~1500 chars for a 15K file.

**Root Cause:** CodeMirror 6 virtualizes long documents, only rendering visible portions in the DOM.

**Fix:** Fetch raw file from GitHub instead:
```javascript
const resp = await fetch('https://raw.githubusercontent.com/OWNER/REPO/BRANCH/path/to/file.py');
const content = await resp.text();
```

---

## Issue #4: Telegram Bot Token - 404 on getUpdates

**Symptom:** `{"ok":false,"error_code":404,"description":"Not Found"}`

**Fix:** Verify token with `/getMe` first. Ensure URL format is exactly `bot` + TOKEN with no spaces.

---

## Issue #5: getUpdates Returns Empty Results

**Fix:** Add bot to group as admin, send a message in the group, then call getUpdates again.

---

## Issue #6: Telegram Topics vs Channels Architecture

**Original Design:** Separate channels with individual chat_ids.

**Actual Setup:** Forum/Topics mode (is_forum: true) in one supergroup.

**Key Change:** All send_message/send_photo calls now include `message_thread_id=settings.TOPIC_*` parameter.

**Config Changes:**
- settings.py: Replaced CHANNEL_* with TOPIC_* variables
- posting.py: Added message_thread_id to all posting functions
- handlers.py: Updated poll command to use MAIN_GROUP + TOPIC_POLLS

**Topic IDs for Guapo Prints!:**
| Topic | Thread ID |
|-------|-----------|
| Announcements | 10 |
| Gallery | 11 |
| Reviews | 12 |
| Tips and Tricks | 13 |
| Requests | 14 |
| Polls | 15 |
| General Chat | 21 |

**How to get topic IDs:** Call `/getUpdates` and look for `forum_topic_created` events with `message_thread_id`.

---

## Issue #7: Telegram for Mac - Cannot Find "New Channel"

**Symptom:** Compose button only shows "Create Topic" inside a Forum group.

**Fix:** Navigate to main chat list first, then click compose. The "New Channel" option only appears outside of group context.

**Resolution:** Used Topics within supergroup instead of separate channels.

---

## Issue #8: PowerShell - >> Continuation Prompt

**Symptom:** `>>` appears instead of executing commands.

**Fix:** Press Ctrl+C to cancel pending input, then proceed normally.

---

## Issue #9: User ID - Leading Zero Dropped

**Symptom:** User provided ID as 051279989, actual ID was 1051279989.

**Fix:** Always verify user IDs from the getUpdates API response (from.id field).

---

## Issue #10: python-multipart Missing

**Symptom:** `RuntimeError: Form data requires "python-multipart"`

**Fix:** Added python-multipart==0.0.12 to requirements.txt.

---

## Development Notes

### Running on Windows
```powershell
cd C:\\3d-print-bot
python run.py          # Bot + Dashboard
python run.py --bot    # Bot only
python run.py --api    # Dashboard only (localhost:8000)
```
Press Ctrl+C to stop. Keep PowerShell open.

### Key Config
- Group ID: -1003783471565 (Guapo Prints!)
- Admin ID: 1051279989 (@el_squancho)
- Bot: @LayerGOD_bot ("Spaghetti Lord")
- Timezone: America/New_York
- Dashboard: http://localhost:8000
- Database: ./data/bot.db (shared between bot and API)

### Architecture
```
Telegram API <-> Bot (main.py) <-> SQLite DB <-> FastAPI (api/server.py) <-> Dashboard (dashboard/index.html)
```
All messages routed to topics via message_thread_id. Scheduled: POTD 9am, Tips 12pm, Gallery scan every 30min.
