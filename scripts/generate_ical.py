import os
import requests
import re
from html import unescape
from datetime import datetime, timezone
from dateutil import parser

OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "docs/calendar.ics")
API_URL = os.environ.get("ENGAGE_API_URL")        # Full Engage URL with query params
API_KEY = os.environ.get("ENGAGE_API_KEY", "")   # X-Engage-Api-Key
TIMEZONE_HINT = os.environ.get("TIMEZONE_HINT", "UTC")


# --------------------------------------------------------------------------
# Utility Functions
# --------------------------------------------------------------------------

def zulu(dt_str):
    """Convert Engage ISO timestamps to UTC Zulu format."""
    if not dt_str:
        return None
    dt = parser.isoparse(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")


def escape_ical(text):
    """Escape special iCal characters."""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
            .replace(",", "\\,")
            .replace(";", "\\;")
            .replace("\n", "\\n")
    )


def strip_html(html):
    """Remove HTML, decode entities, and strip emojis."""
    if not html:
        return ""

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html)
    text = unescape(text)

    # Remove emojis and non-ASCII characters (Google Calendar requirement)
    text = text.encode('ascii', 'ignore').decode()

    # Collapse whitespace
    return " ".join(text.split()).strip()


# --------------------------------------------------------------------------
# Fetch All Pages of Events from Engage
# --------------------------------------------------------------------------

def fetch_all_events():
    """Engage paginates: skip, take, totalItems. We fetch all pages."""
    headers = {
        "accept": "application/json",
        "X-Engage-Api-Key": API_KEY
    }

    events = []
    skip = 0
    take = 50   # You can adjust; 50 is safe

    while True:
        paged_url = f"{API_URL}&skip={skip}&take={take}"

        resp = requests.get(paged_url, headers=headers, timeout=30)
        print(f"Fetching: skip={skip}, status={resp.status_code}")

        if resp.status_code != 200:
            print("Response snippet:", resp.text[:500])
            resp.raise_for_status()

        data = resp.json()

        items = data.get("items", [])
        events.extend(items)

        total = data.get("totalItems", len(items))
        skip += take

        if skip >= total:
            break

    print(f"Fetched {len(events)} events total.")
    return events


# --------------------------------------------------------------------------
# Create VEVENT Blocks
# --------------------------------------------------------------------------

def to_vevent(e):
    eid   = e.get("id")
    title = e.get("name") or ""
    desc  = strip_html(e.get("description") or "")
    start = e.get("startsOn")
    end   = e.get("endsOn")

    # LOCATION formatting
    address = e.get("address") or {}
    name = address.get("name")
    addr = address.get("address")

    if name and addr:
        loc = f"{name}, {addr}".replace(" ,", ",").strip()
    elif name:
        loc = name.strip()
    elif addr:
        loc = addr.strip()
    else:
        loc = ""

    # URL (Engage doesn't provide direct event link in this API)
    url = e.get("imageUrl")

    # STATUS (Canceled events)
    state = e.get("state") or {}
    status = state.get("status")
    is_cancelled = (status and status.lower() == "canceled")

    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = zulu(start)
    dtend   = zulu(end)

    lines = []
    lines.append("BEGIN:VEVENT")
    lines.append(f"UID:{eid}@fairmontstate.edu")
    lines.append(f"DTSTAMP:{dtstamp}")

    if dtstart:
        lines.append(f"DTSTART:{dtstart}")
    if dtend:
        lines.append(f"DTEND:{dtend}")

    lines.append(f"SUMMARY:{escape_ical(title)}")
    if desc:
        lines.append(f"DESCRIPTION:{escape_ical(desc)}")
    if loc:
        lines.append(f"LOCATION:{escape_ical(loc)}")
    if url:
        lines.append(f"URL:{url}")
    if is_cancelled:
        lines.append("STATUS:CANCELLED")

    lines.append("END:VEVENT")
    return lines


# --------------------------------------------------------------------------
# Build the Calendar
# --------------------------------------------------------------------------

def main():
    if not API_URL:
        raise SystemExit("ENGAGE_API_URL is not set!")

    events = fetch_all_events()

    lines = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//Fairmont State//Engage iCal//EN")
    lines.append("CALSCALE:GREGORIAN")
    lines.append("METHOD:PUBLISH")

    for e in events:
        lines.extend(to_vevent(e))

    lines.append("END:VCALENDAR")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(lines))

    print(f"Wrote {OUTPUT_PATH} with {len(events)} events. Timezone hint: {TIMEZONE_HINT}")


if __name__ == "__main__":
    main()
