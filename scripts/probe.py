"""
One-off endpoint probe — verify which API endpoints this league supports.

Run once when setting up the repo (locally or via the workflow's dry-run
dispatch) to see which optional endpoints the league's platform exposes.
fetch.py tolerates missing optional endpoints, so a ✗ here just means that
data won't appear in the repo — nothing breaks.

Usage:
  python3 scripts/probe.py
"""

from __future__ import annotations

import sys

import requests  # type: ignore[import-untyped]

import league_config as cfg

TIMEOUT = 30


def probe(session: requests.Session, label: str, url: str) -> dict | list | None:
    try:
        r = session.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                print(f"  ✗ {label:<28} 200 but not JSON")
                return None
            size = len(data) if isinstance(data, (list, dict)) else "?"
            print(f"  ✓ {label:<28} OK ({type(data).__name__}, {size} top-level items)")
            return data
        print(f"  ✗ {label:<28} HTTP {r.status_code}")
    except Exception as e:
        print(f"  ✗ {label:<28} {e}")
    return None


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": cfg.USER_AGENT})

    print(f"Probing {cfg.LEAGUE_NAME} API — {cfg.API_BASE}")
    print("=" * 60)

    bootstrap = probe(session, "bootstrap-static/", f"{cfg.API_BASE}/bootstrap-static/")
    if not isinstance(bootstrap, dict):
        print("\nFATAL: bootstrap unavailable — nothing else can work.")
        raise SystemExit(1)

    events = bootstrap.get("events", [])
    elements = bootstrap.get("elements", [])
    teams = bootstrap.get("teams", [])
    print(f"      {len(elements)} players, {len(teams)} teams, {len(events)} gameweeks")

    # Pick a real player and a finished GW for the parameterised endpoints
    sample_player = elements[0]["id"] if elements else 1
    finished_gws = [ev["id"] for ev in events if ev.get("finished")]
    sample_gw = finished_gws[0] if finished_gws else 1

    probe(session, "fixtures/", f"{cfg.API_BASE}/fixtures/")
    probe(session, "event-status/", f"{cfg.API_BASE}/event-status/")
    probe(session, f"element-summary/{sample_player}/",
          f"{cfg.API_BASE}/element-summary/{sample_player}/")
    probe(session, f"event/{sample_gw}/live/", f"{cfg.API_BASE}/event/{sample_gw}/live/")
    probe(session, f"dream-team/{sample_gw}/", f"{cfg.API_BASE}/dream-team/{sample_gw}/")
    probe(session, "dream-team/", f"{cfg.API_BASE}/dream-team/")
    probe(session, "team/set-piece-notes/", f"{cfg.API_BASE}/team/set-piece-notes/")
    probe(session, "regions/", f"{cfg.API_BASE}/regions/")

    # Report any xG fields present (these are stripped before saving)
    xg_fields = sorted(
        k for k in (elements[0] if elements else {})
        if k.startswith("expected_")
    )
    print()
    if xg_fields:
        print(f"  xG fields present in bootstrap (stripped on save): {', '.join(xg_fields)}")
    else:
        print("  No xG fields in bootstrap for this league.")

    print("\nDone. ✗ on optional endpoints (dream-team, set-piece-notes, regions,")
    print("event-status) is fine — fetch.py skips them gracefully.")


if __name__ == "__main__":
    main()
