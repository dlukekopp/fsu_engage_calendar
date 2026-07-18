import os
import requests
import re
from html import unescape
from datetime import datetime, timedelta, timezone
from dateutil import parser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "docs/calendar.ics")
API_URL = os.environ.get("ENGAGE_API_URL")        # Full Engage URL with query params
API_KEY = os.environ.get("ENGAGE_API_KEY", "")   # X-Engage-Api-Key
TIMEZONE_HINT = os.environ.get("TIMEZONE_HINT", "UTC")
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))

MAX_PAGES = 200   # Runaway-pagination guard
FALLBACK_DTSTAMP = "19700101T000000Z"


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


def parse_utc(dt_str):
    """Parse an Engage ISO timestamp to an aware UTC datetime, or None."""
    if not dt_str:
        return None
    try:
        dt = parser.isoparse(dt_str)
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Fetch All Pages of Events from Engage
# --------------------------------------------------------------------------

def fetch_all_events(now):
    """Engage paginates: skip, take, totalItems. We fetch all pages."""
    headers = {
        "accept": "application/json",
        "X-Engage-Api-Key": API_KEY
    }

    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))

    base_url = API_URL
    # API_URL is a secret that already embeds query params; don't duplicate
    if "endsAfter" not in API_URL:
        base_url += f"&endsAfter={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    events = []
    skip = 0
    take = 50   # You can adjust; 50 is safe

    for _ in range(MAX_PAGES):
        paged_url = f"{base_url}&skip={skip}&take={take}"

        resp = session.get(paged_url, headers=headers, timeout=30)
        print(f"Fetching: skip={skip}, status={resp.status_code}")

        if resp.status_code != 200:
            print("Response snippet:", resp.text[:500])
            resp.raise_for_status()

        data = resp.json()

        if not isinstance(data, dict) or "items" not in data:
            raise SystemExit(
                f"Unexpected API response shape at skip={skip}: "
                "expected a JSON object with an 'items' key."
            )

        items = data["items"]
        events.extend(items)

        if not items:
            break

        total = data.get("totalItems", len(items))
        skip += take

        if skip >= total:
            break
    else:
        print(f"Warning: hit {MAX_PAGES}-page cap; stopping pagination.")

    print(f"Fetched {len(events)} events total.")
    return events


# --------------------------------------------------------------------------
# Create VEVENT Blocks
# --------------------------------------------------------------------------

def event_dtstamp(e):
    """Deterministic DTSTAMP (never the current time, so reruns don't churn)."""
    for key in ("modifiedOn", "lastModified", "modifiedOnUtc", "startsOn"):
        if parse_utc(e.get(key)) is not None:
            return zulu(e.get(key))
    return FALLBACK_DTSTAMP


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

    dtstamp = event_dtstamp(e)
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

def sort_key(e):
    """Sort by (DTSTART string, UID string); events with no start sort last."""
    start = parse_utc(e.get("startsOn"))
    dtstart = start.strftime("%Y%m%dT%H%M%SZ") if start else "~"
    return (dtstart, str(e.get("id")))


def main():
    if not API_URL:
        raise SystemExit("ENGAGE_API_URL is not set!")

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=WINDOW_DAYS)

    events = fetch_all_events(now)

    # ----------------------------------------------------------------------
    # Date Window Filtering
    # ----------------------------------------------------------------------

    kept = []
    skipped_unparseable = 0

    for e in events:
        start = parse_utc(e.get("startsOn"))
        if start is None:
            skipped_unparseable += 1
            continue
        # Missing/unparseable end falls back to start; >= now keeps in-progress events
        end = parse_utc(e.get("endsOn")) or start
        if end >= now and start < window_end:
            kept.append(e)

    kept.sort(key=sort_key)

    print(f"Fetched {len(events)} events, kept {len(kept)} "
          f"within the next {WINDOW_DAYS} days.")
    if skipped_unparseable:
        print(f"Skipped {skipped_unparseable} events with missing/unparseable startsOn.")

    lines = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//Fairmont State//Engage iCal//EN")
    lines.append("CALSCALE:GREGORIAN")
    lines.append("METHOD:PUBLISH")

    for e in kept:
        lines.extend(to_vevent(e))

    lines.append("END:VCALENDAR")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(lines))

    print(f"Wrote {OUTPUT_PATH} with {len(kept)} events. Timezone hint: {TIMEZONE_HINT}")


if __name__ == "__main__":
    main()
