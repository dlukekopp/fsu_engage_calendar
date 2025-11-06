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

def to_vevent(e):
    # Adjust these keys to match your Engage API shape.
    eid         = e.get("id") or e.get("eventId") or e.get("uuid")
    title       = e.get("title") or e.get("name") or ""
    description = e.get("description") or ""
    location    = e.get("location") or e.get("place") or ""
    url         = e.get("url") or e.get("link")
    start       = e.get("start") or e.get("startTime") or e.get("startsAt")
    end         = e.get("end") or e.get("endTime") or e.get("endsAt")
    updated     = e.get("updatedAt") or e.get("modifiedAt") or e.get("lastModified")

    dtstamp = zulu(updated) or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = zulu(start)
    dtend   = zulu(end)

    uid_domain = os.environ.get("UID_DOMAIN", "fairmontstate.edu")
    uid = f"{eid}@{uid_domain}" if eid else f"{dtstamp}@{uid_domain}"

    lines = []
    lines.append("BEGIN:VEVENT")
    lines.append(f"UID:{uid}")
    lines.append(f"DTSTAMP:{dtstamp}")

    # If you ever need date-only all-day events, add a branch here (VALUE=DATE)
    if dtstart:
        lines.append(f"DTSTART:{dtstart}")
    if dtend:
        lines.append(f"DTEND:{dtend}")

    lines.append(f"SUMMARY:{escape_ical(title)}")
    if description:
        lines.append(f"DESCRIPTION:{escape_ical(description)}")
    if location:
        lines.append(f"LOCATION:{escape_ical(location)}")
    if url:
        lines.append(f"URL:{url}")
    # If your API provides recurrence (RRULE), include it here:
    # if e.get("rrule"):
    #     lines.append(f"RRULE:{e['rrule']}")

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

    # Your endpoint returns:
    # { skip, take, totalItems, items: [...] }
    if isinstance(data, dict) and "items" in data:
        return data["items"]

    # Fallback
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
