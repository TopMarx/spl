"""
Print the current season start year, derived from the live league API.

Fetches bootstrap-static and derives the season from the first event's
deadline_time (see derive_season_from_bootstrap in fetch.py, which respects
the league's SEASON_CONVENTION). Because this reads the API's own data, the
season rolls over exactly when the league API does — not on a calendar date.
During the off-season the old game keeps serving last season's final state,
and this script keeps returning the old season until the new game launches.

Prints the season (e.g. "2026") to stdout and nothing else, so it can be
used in command substitution. Diagnostics go to stderr. Exits non-zero if
the API is unreachable or the season cannot be derived (e.g. during the
between-games maintenance window) — callers should treat that as
"do not fetch today".

Usage:
  SEASON=$(python3 scripts/current_season.py)
"""

from __future__ import annotations

import contextlib
import sys

import requests  # type: ignore[import-untyped]

import league_config as cfg
from fetch import API_BASE, HEADERS, derive_season_from_bootstrap, fetch_json


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # fetch_json prints retry diagnostics to stdout; route them to
        # stderr so stdout carries the season and nothing else.
        with contextlib.redirect_stdout(sys.stderr):
            bootstrap = fetch_json(f"{API_BASE}/bootstrap-static/", session)
        season = derive_season_from_bootstrap(bootstrap)
    except Exception as e:
        print(f"FATAL: could not derive season from {cfg.LEAGUE_NAME} API: {e}", file=sys.stderr)
        raise SystemExit(1)

    print(
        f"Derived season {cfg.season_label(season)} from bootstrap "
        f"events[0].deadline_time",
        file=sys.stderr,
    )
    print(season)


if __name__ == "__main__":
    main()
