# VyatSU → Apple Calendar (prototype v0.1)

Target: **МНб-3601-02-00**, subgroup **01**, PE **Боков А.В.**, Moscow timezone.

Automated update: **once daily at 07:30 Kirov time (04:30 UTC)**. GitHub Actions scheduled runs may be delayed by GitHub; Apple subscription refresh has its own delay.

## Setup
1. Create a **public** GitHub repository and upload these files, including `.github/workflows/sync.yml`.
2. In GitHub Settings → Actions → General, set Workflow permissions to **Read and write permissions**.
3. Open Actions → Update VyatSU calendar → Run workflow. Confirm it completes and creates `calendar.ics`.
4. Settings → Pages → Deploy from a branch → `main` / `(root)`.
5. After Pages publishes, subscribe on iPhone: Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add Subscribed Calendar.
   Enter `https://YOUR_USERNAME.github.io/YOUR_REPOSITORY/calendar.ics`.
6. Keep the repository public only if you're comfortable publishing the university timetable; do not put personal calendar events or secrets here.

## Limitations
- **Unverified against live university PDFs** in the build environment: the code needs an end-to-end test with real PDFs before relying on it.
- University PDF layouts may change; parsing fails closed rather than publishing an empty calendar.
- The site currently lists only published 2-week periods; future unpublished classes cannot be included.
- Apple controls how frequently a subscribed calendar refreshes.
- PE electives are filtered to subgroup 01 and Боков А.В.; all other PE variants are excluded.
- The script does not modify your existing Apple calendars; subscription is read-only.
- If an event changes its time, the event UID changes and Apple may briefly show stale entries until subscription refresh.

## Local test
`pip install -r requirements.txt && python sync.py`
