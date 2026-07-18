# FSU Engage Calendar

Pulls upcoming events from the FSU Engage API and publishes `docs/calendar.ics` for campus digital signage. Runs hourly via GitHub Actions.

## Feed URL

Signage consumes the raw file on `main`:

```
https://raw.githubusercontent.com/dlukekopp/fsu_engage_calendar/main/docs/calendar.ics
```

**Do not move or rename this path.** Signage players point directly at it; changing it breaks every screen.

## How it works

- The workflow (`.github/workflows/build-ical.yml`) runs on an hourly cron (plus manual dispatch and pushes to `scripts/`).
- `scripts/generate_ical.py` fetches events from Engage that end after now, keeping a 30-day forward window.
- The script writes `docs/calendar.ics`.
- The workflow commits the file only when event content actually changed.

## Configuration

Env vars set in the workflow:

| Variable | Description |
| --- | --- |
| `ENGAGE_API_URL` | Repo secret. Full Engage events API URL, including query params. |
| `ENGAGE_API_KEY` | Repo secret. Sent as the `X-Engage-Api-Key` header. |
| `WINDOW_DAYS` | Days ahead to include (default 30). Signage shows ~48h, so this gives a large buffer if updates break. |
| `OUTPUT_PATH` | Output file path (default `docs/calendar.ics`). |
| `TIMEZONE_HINT` | Informational only. |

## Reliability notes

- The workflow's final step resets GitHub's 60-day scheduled-workflow auto-disable timer each run, so the cron keeps firing through long no-commit stretches.
- If the Engage API errors, the run fails and the last good calendar stays published.
- A manual run is available via the Actions tab (`workflow_dispatch`).
