# Fantasy Saudi Pro League

Fantasy Saudi Pro League fantasy game data, fetched directly from the official fantasy API at
`https://en.fantasy.spl.com.sa/api/`.

Data is available as raw JSON (exactly as returned by the API) and as
processed CSVs for easy use in spreadsheets, notebooks, and analysis tools.

This repository is a sibling of [TopMarx/fpl](https://github.com/TopMarx/fpl) —
the league's fantasy game runs on the same platform as Fantasy Premier League,
so the data model and pipeline are the same. The only league-specific file is
`scripts/league_config.py`.

---

## Repository structure

```
.
├── .github/workflows/
│   └── spl-fetch.yml                # scheduled daily fetch (1am UTC, retries 2am/3am)
├── scripts/
│   ├── league_config.py             # league-specific settings — the only per-league file
│   ├── fetch.py                     # smart daily fetch
│   ├── generate_csv.py              # JSON → CSV
│   ├── generate_latest.py           # builds latest/
│   └── current_season.py            # derives the current season from the API
├── data/
│   └── {season}/                    # one directory per season, e.g. 2026/
│       ├── spl-bootstrap_{season}.json
│       ├── spl-fixtures_{season}.json
│       ├── spl-dream-team_{season}.json
│       ├── spl-regions_{season}.json
│       ├── fetch-manifest.json      # state of the most recent fetch
│       ├── players/                 # one JSON per player (full match history)
│       ├── gameweeks/
│       │   └── gw{N}/               # live.json + dream-team.json per GW
│       └── csv/                     # processed CSVs (players, teams, fixtures,
│           └── players/             #   gameweeks, live, dream-teams, regions,
│                                    #   per-player history & history_past)
└── latest/                          # always the most recent data, season-agnostic
    ├── spl-bootstrap.json
    ├── spl-fixtures.json
    ├── players-{team_opta_id}.json  # one per team
    ├── players-history-past.json
    └── fetch-manifest.json
```

## What's included

### JSON (raw API data)

| File | Description |
|---|---|
| `data/{season}/spl-bootstrap_{season}.json` | Players, teams, gameweeks, game settings |
| `data/{season}/spl-fixtures_{season}.json` | All season fixtures with scores |
| `data/{season}/players/{player_id}_{first}_{second}_{opta_id}.json` | Per-player match history |
| `data/{season}/gameweeks/gw{N}/live.json` | Live points and stats per GW |
| `data/{season}/gameweeks/gw{N}/dream-team.json` | GW dream team |
| `data/{season}/spl-dream-team_{season}.json` | Season dream team (updated each GW) |
| `data/{season}/spl-regions_{season}.json` | Region/nationality reference (if the league API provides it) |

Unlike FPL, this league's platform does not provide the `event-status/`
or `team/set-piece-notes/` endpoints (verified across all sibling league
platforms). The pipeline skips them gracefully — and still attempts them,
so if the platform ever adds them the data will be collected automatically.

### CSV (processed)

| File | Description |
|---|---|
| `data/{season}/csv/players.csv` | All players with season stats and metadata |
| `data/{season}/csv/teams.csv` | All teams listed in the bootstrap (18 compete in Saudi Pro League; the platform may list extra historical entries) |
| `data/{season}/csv/fixtures.csv` | All fixtures with scores |
| `data/{season}/csv/players/history/{player_id}_{first}_{second}_{opta_id}.csv` | Per-player match history |
| `data/{season}/csv/players/history_past/{player_id}_{first}_{second}_{opta_id}.csv` | Player season histories |
| `data/{season}/csv/gameweeks.csv` | Gameweek summary data |
| `data/{season}/csv/live.csv` | Per-player points and stats for each GW |
| `data/{season}/csv/dream-teams.csv` | GW and season dream teams |
| `data/{season}/csv/regions.csv` | Region/nationality reference |

### Latest (always current season)

The `latest/` directory always reflects the most recently fetched data,
without needing to know the current season year:

| File | Description |
|---|---|
| `latest/spl-bootstrap.json` | Current bootstrap |
| `latest/spl-fixtures.json` | Current fixtures |
| `latest/players-{team_opta_id}.json` | Per-team player histories (one file per team) |
| `latest/fetch-manifest.json` | Fetch metadata and completion status |
| `latest/players-history-past.json` | Previous-season summaries per player (regenerated on GW closure) |

---

## Update schedule

The repository updates automatically via GitHub Actions:

- **Daily at 1am UTC** — fetches bootstrap, fixtures, and player data for any
  teams that played the previous day
- **On gameweek closure** — full fetch of all players once a gameweek is
  confirmed complete (`finished` and `data_checked` both true in the bootstrap),
  plus live points, GW dream team, season dream team, and regions

On most days with no matches, only bootstrap and fixtures are refreshed.
Player element-summary files are only fetched when needed, keeping API
usage polite and minimal.

If match data is still being processed at 1am, retries run automatically at 2am
and 3am UTC.

### Season rollover

The season is derived from the league API itself — the first gameweek's
`deadline_time` in the bootstrap — never from the calendar. A season guard
in `fetch.py` aborts before writing anything if the requested season doesn't
match what the API is actually serving, so each `data/{season}` directory is
guaranteed to contain only that season's data.

During the off-season the old game keeps serving the finished season's final
state, and daily runs quietly refresh it under the old season label. If the
platform takes the API down to launch the new game, scheduled runs fail —
this is expected. Once the new game is live, the next run derives the new
season and creates its `data/{season}` directory automatically.

---

## Player files

Each player has their own JSON file named:

```
{player_id}_{first_name}_{second_name}_{opta_id}.json
```

`player_id` is the API's per-season `id`; `opta_id` is the API's stable
`code` — the Opta player ID, consistent across seasons and competitions. The file contains the player's match-by-match history for the current
season (`history`) and season summaries for previous seasons (`history_past`),
exactly as returned by the `element-summary/{player_id}/` endpoint.

Player files are organised by season under `data/{season}/players/`.

---

## Season format

Seasons span two calendar years and are identified by their start year. The 2026/27 season is `2026`.

The current season is determined from the league API's own data, not the
calendar — see [Season rollover](#season-rollover) above.

---

## Fetch manifest

Each season directory contains a `fetch-manifest.json` recording the state
of the most recent fetch:

```json
{
  "season": 2025,
  "last_run": "2026-01-15T01:15:32Z",
  "current_gw": 12,
  "fetch_type": "active_gw",
  "expected_count": 60,
  "fetched_count": 60,
  "failed_ids": [],
  "completed": true,
  "last_closed_gw": 11
}
```

`fetch_type` values:

| Value | Meaning |
|---|---|
| `active_gw` | Fetched players for teams that played yesterday |
| `gw_closure` | Full fetch of all players on GW closure |
| `forced` | Manual full fetch via workflow dispatch |
| `none` | No matches yesterday, nothing to fetch |
| `waiting` | GW finished but data not yet checked |
| `blocked` | Match data still processing, retrying next run |

---

## API endpoints covered

All data is sourced from the public fantasy API at
`https://en.fantasy.spl.com.sa/api/`:

| Endpoint | Data |
|---|---|
| `bootstrap-static/` | Players, teams, gameweeks |
| `fixtures/` | All season fixtures |
| `element-summary/{id}/` | Per-player match history |
| `event/{gw}/live/` | Live GW points and stats |
| `dream-team/{gw}/` | GW dream team |
| `dream-team/` | Season dream team |
| `regions/` | Nationality/region reference |

Only public, read-only game data is collected. The platform also has
endpoints for individual fantasy managers' teams and picks, mini-league
standings, and login-protected actions (my-team, transfers) — none of
those are fetched or stored here.

---

## Using the data

### Python

```python
import json
import urllib.request

# Latest bootstrap
url = "https://raw.githubusercontent.com/TopMarx/spl/main/latest/spl-bootstrap.json"
with urllib.request.urlopen(url) as r:
    bootstrap = json.loads(r.read())

players = bootstrap["elements"]
teams = bootstrap["teams"]
```

### Direct download

Raw files are available at:
```
https://raw.githubusercontent.com/TopMarx/spl/main/data/{season}/spl-bootstrap_{season}.json
https://raw.githubusercontent.com/TopMarx/spl/main/latest/spl-bootstrap.json
```

### Clone the repo

```
git clone https://github.com/TopMarx/spl.git
```

---

## Note on data

xG metrics (`expected_goals`, `expected_assists`, and related per-90 fields)
are stripped before saving where the league's platform provides them, as they
are Opta-licensed. All other fields are stored exactly as returned by the API.

## License

MIT — see [LICENSE](LICENSE). The underlying data belongs to the league and
its data providers.
