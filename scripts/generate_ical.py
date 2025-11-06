import os
import json
import requests
from datetime import datetime, timezone
from dateutil import parser

OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "docs/calendar.ics")
API_URL = os.environ.get("ENGAGE_API_URL")           # e.g., https://api.example.edu/engage/events
API_KEY = os.environ.get("ENGAGE_API_KEY", "")       # if your API requires a bearer/token key
TIMEZONE_HINT = os.environ.get("TIMEZONE_HINT", "UTC")  # optional; used only for logging

def zulu(dt_str):
    """Convert an ISO-like string to UTC Zulu (YYYYMMDDTHHMMSSZ)."""
    if not dt_str:
        return None
    dt = parser.isoparse(dt_str)
    if dt.tzinfo is None:
        # Treat naive times as UTC if the API returns naive values.
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")

def escape_ical(text):
    """Escape characters that iCal requires to be escaped."""
    if not text:
        return ""
    return (
        text
        .replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )

import re
from html import unescape

def strip_html(html):
    """Remove HTML tags & decode entities."""
    if not html:
        return ""
    # Remove tags
    text = re.sub(r'<[^>]+>', '', html)
    # Decode HTML entities (&nbsp;, etc.)
    return unescape(text).strip()


def to_vevent(e):
    eid     = e.get("id")
    title   = e.get("name") or ""
    desc    = strip_html(e.get("description") or "")
    start   = e.get("startsOn")
    end     = e.get("endsOn")

    # location: use the Engage address block
    address = e.get("address") or {}
    location_name = address.get("name")
    location_addr = address.get("address")
    loc = ""
    if location_name and location_addr:
        loc = f"{location_name}, {location_addr}"
    elif location_name:
        loc = location_name
    elif location_addr:
        loc = location_addr

    # URL: Engage does not return canonical event page URL in this endpoint.
    # We'll use imageUrl or leave URL off.
    url = e.get("imageUrl")

    # State block can mark events as Canceled
    status_block = e.get("state") or {}
    status = status_block.get("status")  # Approved, Canceled, etc.

    # Canceled events → mark them with STATUS:CANCELLED
    is_cancelled = status and status.lower() == "canceled"

    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    dtstart = zulu(start) if start else None
    dtend   = zulu(end) if end else None

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


def fetch_events():
    headers = {
        "accept": "application/json",
        "X-Engage-Api-Key": API_KEY
    }

    resp = requests.get(API_URL, headers=headers, timeout=30)

    print("Status code:", resp.status_code)
    print("Response snippet:", resp.text[:500])

    resp.raise_for_status()
    data = resp.json()

    # Engage event list format:
    # { skip, take, totalItems, items: [ ... ] }
    if isinstance(data, dict) and "items" in data:
        return data["items"]

    return data



def main():
    if not API_URL:
        raise SystemExit("ENGAGE_API_URL is not set. Configure it as a GitHub Secret.")

    events = fetch_events()

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
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines))

    print(f"Wrote {OUTPUT_PATH} with {len(events)} events (source tz hint: {TIMEZONE_HINT}).")

if __name__ == "__main__":
    main()
