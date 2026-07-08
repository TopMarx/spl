"""
Fantasy API Smart Fetch Script (league-agnostic)

League-specific values (API base, file prefix, season convention) come from
league_config.py — everything else is identical across league repos.

Checks GW state daily and fetches only what's needed.

Always fetches:
  - bootstrap-static
  - fixtures

On GW closure or forced fetch, also fetches:
  - event/{gw}/live/ (per GW)
  - dream-team/{gw}/ (per GW)
  - dream-team/ (season)
  - team/set-piece-notes/
  - regions/
  (Not every league platform exposes all of these — failures on the
  optional extras are logged and do not fail the run. Run probe.py once
  to see which endpoints your league supports.)

Checks event-status before any player fetch to ensure all match data
is fully processed (points: "r"). If any match is live or unprocessed,
exits cleanly — the workflow retries at the next scheduled runs.

Fetches player element-summaries when:
  - Matches were played yesterday (active GW): all players on teams that
    have played any match in the current GW so far (catches stat revisions)
  - GW closure (finished + data_checked both True, not yet recorded in
    manifest): all players

Failed players are retried once at the end of each run. Persistent failures
are recorded in the manifest by player ID for visibility.

The manifest (fetch-manifest.json) is committed back to the repo between
GitHub Actions runs to persist state across VM instances.

Season guard: after downloading the bootstrap, the season is derived from
the first event's deadline_time and compared against --season. On mismatch
the script exits (code 1) before writing anything. This prevents the old
season's data being written under a new season label during the off-season
window when the API has not yet rolled over (the calendar says the new
season has started, but the API is still serving last season's final state).

Usage:
  python3 fetch.py --season 2026 --output data/2026
  python3 fetch.py --season 2026 --output data/2026 --date 2026-07-10
  python3 fetch.py --season 2026 --output data/2026 --force
  python3 fetch.py --season 2026 --output data/2026 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests  # type: ignore[import-untyped]

import league_config as cfg

API_BASE = cfg.API_BASE
SLUG = cfg.LEAGUE_SLUG
HEADERS = {
    "User-Agent": cfg.USER_AGENT,
}

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4]  # seconds between retries

# Default delay between API requests
DEFAULT_DELAY = 1.5


# ─── HTTP ─────────────────────────────────────────────────────

def fetch_json(url: str, session: requests.Session, retries: int = MAX_RETRIES):
    """Fetch JSON with retry and exponential backoff. 404s are not retried."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise
            last_exc = e
        except Exception as e:
            last_exc = e

        if attempt < retries - 1:
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            print(f"    Retry {attempt + 1}/{retries - 1} in {wait}s...")
            time.sleep(wait)

    raise last_exc or RuntimeError(f"Failed to fetch {url} after {retries} attempts")


# ─── Accent Stripping ─────────────────────────────────────────
# Used only for filename generation — data files store names as-is.

_LATIN_MAP = str.maketrans({
    # Unicode hyphens → ASCII hyphen
    '\u2010': '-', '\u2011': '-',
    # Latin-1 Supplement
    '\xc0': 'A', '\xc1': 'A', '\xc2': 'A', '\xc3': 'A', '\xc4': 'A', '\xc5': 'A',
    '\xe0': 'a', '\xe1': 'a', '\xe2': 'a', '\xe3': 'a', '\xe4': 'a', '\xe5': 'a',
    '\xc7': 'C', '\xe7': 'c',
    '\xd0': 'D', '\xf0': 'd',
    '\xc8': 'E', '\xc9': 'E', '\xca': 'E', '\xcb': 'E',
    '\xe8': 'e', '\xe9': 'e', '\xea': 'e', '\xeb': 'e',
    '\xcc': 'I', '\xcd': 'I', '\xce': 'I', '\xcf': 'I',
    '\xec': 'i', '\xed': 'i', '\xee': 'i', '\xef': 'i',
    '\xd1': 'N', '\xf1': 'n',
    '\xd2': 'O', '\xd3': 'O', '\xd4': 'O', '\xd5': 'O', '\xd6': 'O', '\xd8': 'O',
    '\xf2': 'o', '\xf3': 'o', '\xf4': 'o', '\xf5': 'o', '\xf6': 'o', '\xf8': 'o',
    '\xd9': 'U', '\xda': 'U', '\xdb': 'U', '\xdc': 'U',
    '\xf9': 'u', '\xfa': 'u', '\xfb': 'u', '\xfc': 'u',
    '\xdd': 'Y', '\xfd': 'y', '\xff': 'y',
    '\xc6': 'Ae', '\xe6': 'ae',
    '\xde': 'Th', '\xfe': 'th',
    '\xdf': 'ss',
    # Latin Extended-A
    '\u0100': 'A', '\u0102': 'A', '\u0104': 'A',
    '\u0101': 'a', '\u0103': 'a', '\u0105': 'a',
    '\u0106': 'C', '\u0108': 'C', '\u010a': 'C', '\u010c': 'C',
    '\u0107': 'c', '\u0109': 'c', '\u010b': 'c', '\u010d': 'c',
    '\u010e': 'D', '\u0110': 'D', '\u010f': 'd', '\u0111': 'd',
    '\u0112': 'E', '\u0114': 'E', '\u0116': 'E', '\u0118': 'E', '\u011a': 'E',
    '\u0113': 'e', '\u0115': 'e', '\u0117': 'e', '\u0119': 'e', '\u011b': 'e',
    '\u011c': 'G', '\u011e': 'G', '\u0120': 'G', '\u0122': 'G',
    '\u011d': 'g', '\u011f': 'g', '\u0121': 'g', '\u0123': 'g',
    '\u0124': 'H', '\u0126': 'H', '\u0125': 'h', '\u0127': 'h',
    '\u0128': 'I', '\u012a': 'I', '\u012c': 'I', '\u012e': 'I', '\u0130': 'I',
    '\u0129': 'i', '\u012b': 'i', '\u012d': 'i', '\u012f': 'i', '\u0131': 'i',
    '\u0134': 'J', '\u0135': 'j',
    '\u0136': 'K', '\u0137': 'k', '\u0138': 'k',
    '\u0139': 'L', '\u013b': 'L', '\u013d': 'L', '\u013f': 'L', '\u0141': 'L',
    '\u013a': 'l', '\u013c': 'l', '\u013e': 'l', '\u0140': 'l', '\u0142': 'l',
    '\u0143': 'N', '\u0145': 'N', '\u0147': 'N', '\u014a': 'N',
    '\u0144': 'n', '\u0146': 'n', '\u0148': 'n', '\u014b': 'n',
    '\u014c': 'O', '\u014e': 'O', '\u0150': 'O',
    '\u014d': 'o', '\u014f': 'o', '\u0151': 'o',
    '\u0154': 'R', '\u0156': 'R', '\u0158': 'R',
    '\u0155': 'r', '\u0157': 'r', '\u0159': 'r',
    '\u015a': 'S', '\u015c': 'S', '\u015e': 'S', '\u0160': 'S',
    '\u015b': 's', '\u015d': 's', '\u015f': 's', '\u0161': 's',
    '\u0162': 'T', '\u0164': 'T', '\u0166': 'T',
    '\u0163': 't', '\u0165': 't', '\u0167': 't',
    '\u0168': 'U', '\u016a': 'U', '\u016c': 'U', '\u016e': 'U', '\u0170': 'U', '\u0172': 'U',
    '\u0169': 'u', '\u016b': 'u', '\u016d': 'u', '\u016f': 'u', '\u0171': 'u', '\u0173': 'u',
    '\u0174': 'W', '\u0175': 'w',
    '\u0176': 'Y', '\u0177': 'y', '\u0178': 'Y',
    '\u0179': 'Z', '\u017b': 'Z', '\u017d': 'Z',
    '\u017a': 'z', '\u017c': 'z', '\u017e': 'z',
    '\u0132': 'IJ', '\u0133': 'ij',
    '\u0152': 'Oe', '\u0153': 'oe',
    '\u0149': "'n", '\u017f': 's',
})

_COMBINING_RE = re.compile(r'[\u0300-\u036f\ufe20-\ufe2f\u20d0-\u20ff]')


def strip_accents(value: str) -> str:
    """Transliterate accented/special characters to ASCII equivalents."""
    if not value or not value.strip():
        return value
    s = str(value)
    s = s.replace('\u2019', "'").replace('\u2018', "'")
    s = s.replace('\u201c', '"').replace('\u201d', '"')
    s = s.translate(_LATIN_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = _COMBINING_RE.sub("", s)
    return s.encode("ascii", "ignore").decode("ascii")


def safe_filename(name: str) -> str:
    """Strip accents and convert to a safe ASCII filename component."""
    s = strip_accents(name)
    s = s.replace(" ", "_")
    s = re.sub(r"[^a-zA-Z0-9_\-]", "", s)
    return s


# ─── Opta Stripping ───────────────────────────────────────────
# xG and related metrics are Opta-licensed. Strip before saving.
# Leagues whose platform doesn't carry these fields are unaffected
# (the strip is a no-op).

OPTA_FIELDS = {
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "expected_goals_conceded",
    "expected_goals_per_90",
    "expected_assists_per_90",
    "expected_goal_involvements_per_90",
    "expected_goals_conceded_per_90",
}


def strip_opta_fields(data: dict | list) -> dict | list:
    """Recursively remove Opta-licensed fields from API data before saving."""
    if isinstance(data, list):
        return [strip_opta_fields(item) for item in data]
    if isinstance(data, dict):
        return {
            k: (
                [e for e in v if e.get("name") not in OPTA_FIELDS]
                if k == "element_stats"
                else strip_opta_fields(v)
            )
            for k, v in data.items()
            if k not in OPTA_FIELDS
        }
    return data


# ─── Helper ───────────────────────────────────────────────────

def set_github_outputs(gw_number: int | str, fetch_type: str) -> None:
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        gw_label = f"GW{gw_number} " if gw_number else ""
        with open(github_output, "a") as f:
            f.write(f"gw_number={gw_number}\n")
            f.write(f"gw_label={gw_label}\n")
            f.write(f"fetch_type={fetch_type}\n")


# ─── Manifest ─────────────────────────────────────────────────

def read_manifest(output: Path) -> dict:
    """Read existing manifest or return empty dict."""
    manifest_path = output / "fetch-manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def write_manifest(output: Path, manifest: dict) -> None:
    """Write manifest to disk."""
    manifest["last_run"] = datetime.now(timezone.utc).isoformat()
    manifest_path = output / "fetch-manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  → {manifest_path}")


# ─── Event Status ─────────────────────────────────────────────

def check_event_status(session: requests.Session, yesterday) -> tuple[bool, str]:
    """
    Fetch event-status and check whether all recent match data is processed.
    Blocks if any match on or before yesterday shows points='l' (live) or
    points='' (unprocessed). Only proceeds when all show points='r'.
    Returns (ok_to_fetch, reason).
    """
    try:
        status_data = fetch_json(f"{API_BASE}/event-status/", session)
    except Exception as e:
        print(f"  WARNING: Could not fetch event-status: {e} — proceeding anyway")
        return True, "event-status unavailable"

    for entry in status_data.get("status", []):
        date_str = entry.get("date", "")
        points = entry.get("points", "")
        try:
            match_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        if match_date > yesterday:
            continue  # Future fixture — ignore

        if points == "l":
            return False, f"match on {date_str} is still live (points='l')"
        if points == "":
            return False, f"match on {date_str} has not yet been processed (points='')"

    return True, "all matches processed"


# ─── Season Derivation ────────────────────────────────────────

def derive_season_from_bootstrap(bootstrap: dict) -> int:
    """
    Derive the season start year from the bootstrap itself.

    Uses the first event's deadline_time:
      cross_year leagues    — a deadline in Jul-Dec belongs to a season
                              starting that year; Jan-Jun belongs to the
                              season that started the previous year.
      calendar_year leagues — the season is simply the deadline's year
                              (spring-autumn seasons never span new year).

    Because this reads the API's own data, it rolls over exactly when the
    league API does — not when the calendar does.

    Raises ValueError if the bootstrap has no parseable first deadline;
    callers should treat that as fatal rather than guess.
    """
    events = bootstrap.get("events") or []
    if not events:
        raise ValueError("bootstrap has no events — cannot derive season")

    deadline = events[0].get("deadline_time")
    if not deadline:
        raise ValueError("bootstrap events[0] has no deadline_time — cannot derive season")

    try:
        dt = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"cannot parse events[0].deadline_time {deadline!r}: {e}") from e

    if cfg.SEASON_CONVENTION == "calendar_year":
        return dt.year
    return dt.year if dt.month >= 7 else dt.year - 1


# ─── GW State ─────────────────────────────────────────────────

def get_current_gw(bootstrap: dict) -> dict | None:
    """Find the current gameweek event from bootstrap."""
    for event in bootstrap.get("events", []):
        if event.get("is_current"):
            return event
    return None


def get_teams_played_in_gw(fixtures: list, gw: int) -> set[int]:
    """Get team IDs that have played any finished match in the given GW."""
    teams = set()
    for fix in fixtures:
        if fix.get("event") == gw and fix.get("finished"):
            teams.add(fix["team_h"])
            teams.add(fix["team_a"])
    return teams


def get_fixtures_on_date(fixtures: list, target_date) -> list:
    """Find finished fixtures with a kickoff on the target date (UTC)."""
    matched = []
    for fix in fixtures:
        if not fix.get("finished"):
            continue
        ko = fix.get("kickoff_time")
        if not ko:
            continue
        try:
            ko_dt = datetime.fromisoformat(ko.replace("Z", "+00:00"))
            if ko_dt.date() == target_date:
                matched.append(fix)
        except (ValueError, TypeError):
            continue
    return matched


# ─── Player Fetch ─────────────────────────────────────────────

def fetch_player(el: dict, players_dir: Path, session: requests.Session, delay: float) -> bool:
    """
    Fetch element-summary for a single player. Returns True on success.
    Filename convention: {player_id}_{first}_{second}_{opta_id}.json
    """
    player_id = el["id"]
    opta_id = el["code"]
    first = safe_filename(el.get("first_name", ""))
    second = safe_filename(el.get("second_name", ""))
    player_name = (
        f"{first}_{second}" if first and second
        else safe_filename(el.get("web_name", str(player_id)))
    )
    filename = f"{player_id}_{player_name}_{opta_id}.json"
    filepath = players_dir / filename

    try:
        data = fetch_json(f"{API_BASE}/element-summary/{player_id}/", session)
        for old_file in players_dir.glob(f"{player_id}_*.json"):
            old_file.unlink()
        with open(filepath, "w") as f:
            json.dump(strip_opta_fields(data), f, indent=2)
        time.sleep(delay)
        return True
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            print(f"  SKIP: {player_name} (player ID {player_id}): not found (404)")
        else:
            print(f"  ERROR: {player_name} (player ID {player_id}): {e}")
        time.sleep(delay)
        return False
    except Exception as e:
        print(f"  ERROR: {player_name} (player ID {player_id}): {e}")
        time.sleep(delay)
        return False


def fetch_players(
    elements: list,
    team_ids: set[int] | None,
    players_dir: Path,
    session: requests.Session,
    delay: float,
    dry_run: bool,
) -> tuple[int, int, list[int]]:
    """
    Fetch element-summary for qualifying players.
    team_ids=None fetches all players.
    Failed players are retried once at the end.
    Returns (expected, fetched, persistent_failed_ids).
    """
    if team_ids is None:
        qualifying = elements
        print(f"  Fetching all {len(qualifying)} players")
    else:
        qualifying = [el for el in elements if el["team"] in team_ids]
        print(f"  Fetching {len(qualifying)} players across {len(team_ids)} teams")

    expected = len(qualifying)

    if dry_run:
        print(f"  DRY RUN — would fetch {expected} element summaries")
        return expected, expected, []

    print(f"  Estimated time: ~{expected * delay / 60:.0f} minutes")

    failed_elements: list[dict] = []

    for i, el in enumerate(qualifying):
        success = fetch_player(el, players_dir, session, delay)
        if not success:
            failed_elements.append(el)

        if (i + 1) % 100 == 0 or (i + 1) == expected:
            remaining = (expected - (i + 1)) * delay / 60
            print(f"  {i + 1}/{expected} fetched (~{remaining:.0f}min remaining)...")

    # ── Retry failed players ──────────────────────────────────
    persistent_failed_ids: list[int] = []

    if failed_elements:
        print(f"\n  Retrying {len(failed_elements)} failed player(s)...")
        for el in failed_elements:
            success = fetch_player(el, players_dir, session, delay)
            if not success:
                persistent_failed_ids.append(el["id"])

    fetched = expected - len(persistent_failed_ids)

    if persistent_failed_ids:
        print(f"\n  {len(persistent_failed_ids)} player(s) failed after retry:")
        for player_id in persistent_failed_ids:
            print(f"    player ID {player_id}")

    return expected, fetched, persistent_failed_ids


# ─── GW Extra Fetch ───────────────────────────────────────────

def fetch_gw_extras(gw: int, gameweeks_dir: Path, session: requests.Session, dry_run: bool) -> None:
    """Fetch live points and dream team for a single GW."""
    gw_dir = gameweeks_dir / f"gw{gw}"
    if not dry_run:
        gw_dir.mkdir(parents=True, exist_ok=True)

    for name, url in [
        ("live.json", f"{API_BASE}/event/{gw}/live/"),
        ("dream-team.json", f"{API_BASE}/dream-team/{gw}/"),
    ]:
        try:
            data = fetch_json(url, session)
            if not dry_run:
                path = gw_dir / name
                with open(path, "w") as f:
                    json.dump(strip_opta_fields(data), f, indent=2)
                print(f"  → {path}")
        except Exception as e:
            print(f"  ERROR: GW{gw} {name}: {e}")


def fetch_season_extras(output: Path, season: int, session: requests.Session, dry_run: bool) -> None:
    """Fetch season dream team, set-piece notes, and regions.

    Not every league platform exposes all of these — a 404 here is logged
    and skipped, never fatal.
    """
    for name, url in [
        (f"{SLUG}-dream-team_{season}.json", f"{API_BASE}/dream-team/"),
        (f"{SLUG}-set-piece-notes_{season}.json", f"{API_BASE}/team/set-piece-notes/"),
        (f"{SLUG}-regions_{season}.json", f"{API_BASE}/regions/"),
    ]:
        try:
            data = fetch_json(url, session)
            if not dry_run:
                path = output / name
                with open(path, "w") as f:
                    json.dump(strip_opta_fields(data), f, indent=2)
                print(f"  → {path}")
        except Exception as e:
            print(f"  ERROR: {name}: {e}")


# ─── Main ─────────────────────────────────────────────────────

def run(args):
    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else (datetime.now(timezone.utc) - timedelta(days=1)).date()
    )

    output = Path(args.output)
    # NOTE: output dir is only created after the season guard passes
    # (see step [1/5]) so a mismatched run leaves no empty season dir.
    players_dir = output / "players"

    print(f"{cfg.LEAGUE_NAME} Fetch — Season {cfg.season_label(args.season)}")
    print(f"Output: {output}")
    print(f"Checking for matches on: {target_date}")
    if args.dry_run:
        print("Mode: DRY RUN")
    print("=" * 60)

    # ── Read manifest ─────────────────────────────────────────
    manifest = read_manifest(output)
    if manifest:
        print(f"\n  Manifest: last run {manifest.get('last_run', 'unknown')}")
        print(f"  Last GW closure recorded: GW{manifest.get('last_closed_gw', 'none')}")

    session = requests.Session()
    session.headers.update(HEADERS)

    # ── 1. Bootstrap ──────────────────────────────────────────
    print("\n[1/5] Fetching bootstrap-static...")
    try:
        bootstrap = fetch_json(f"{API_BASE}/bootstrap-static/", session)
    except Exception as e:
        print(f"  FATAL: Failed to fetch bootstrap after {MAX_RETRIES} attempts: {e}")
        raise SystemExit(1)

    # ── Season guard ──────────────────────────────────────────
    # The API's own data is the source of truth for which season this is.
    # Abort before writing anything if it disagrees with --season.
    try:
        api_season = derive_season_from_bootstrap(bootstrap)
    except ValueError as e:
        print(f"  FATAL: Season guard failed — {e}")
        raise SystemExit(1)

    if api_season != args.season:
        print(f"  FATAL: Season mismatch — the API is serving season "
              f"{cfg.season_label(api_season)}, but --season {args.season} "
              f"was given. Nothing written.")
        print("  (Expected during the off-season if the caller derives the season "
              "from the calendar; the API rolls over at new-game launch, not on "
              "a calendar date.)")
        raise SystemExit(1)

    print(f"  Season guard OK: API confirms season {cfg.season_label(api_season)}")

    output.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        bootstrap_path = output / f"{SLUG}-bootstrap_{args.season}.json"
        with open(bootstrap_path, "w") as f:
            json.dump(strip_opta_fields(bootstrap), f, indent=2)
        print(f"  → {bootstrap_path}")

    elements = [
        el for el in bootstrap.get("elements", [])
        if cfg.MANAGER_ELEMENT_TYPE is None
        or el.get("element_type") != cfg.MANAGER_ELEMENT_TYPE
    ]
    print(f"  {len(elements)} players, {len(bootstrap.get('teams', []))} teams")

    # ── 2. Fixtures ───────────────────────────────────────────
    print("\n[2/5] Fetching fixtures...")
    try:
        fixtures = fetch_json(f"{API_BASE}/fixtures/", session)
    except Exception as e:
        print(f"  FATAL: Failed to fetch fixtures after {MAX_RETRIES} attempts: {e}")
        raise SystemExit(1)

    if not args.dry_run:
        fixtures_path = output / f"{SLUG}-fixtures_{args.season}.json"
        with open(fixtures_path, "w") as f:
            json.dump(strip_opta_fields(fixtures), f, indent=2)
        print(f"  → {fixtures_path}")

    finished_count = sum(1 for fix in fixtures if fix.get("finished"))
    print(f"  {len(fixtures)} fixtures ({finished_count} finished)")

    team_lookup = {t["id"]: t for t in bootstrap.get("teams", [])}

    # ── 3. GW state ───────────────────────────────────────────
    print("\n[3/5] Checking GW state...")

    current_gw = get_current_gw(bootstrap)
    if not current_gw:
        print("  No current GW — off season or between seasons. Nothing to fetch.")
        manifest.update({"season": args.season, "fetch_type": "none", "reason": "no current GW"})
        write_manifest(output, manifest)
        set_github_outputs("", "none")
        print("\nDone!")
        return

    gw_number = current_gw["id"]
    gw_finished = current_gw.get("finished", False)
    gw_data_checked = current_gw.get("data_checked", False)
    last_closed_gw = manifest.get("last_closed_gw") or 0

    print(f"  Current GW: {gw_number}")
    print(f"  finished: {gw_finished}, data_checked: {gw_data_checked}")
    print(f"  Last closed GW in manifest: {last_closed_gw}")

    # ── 4. Decide what to fetch ───────────────────────────────
    print("\n[4/5] Determining fetch scope...")

    fetch_type = "none"
    team_ids: set[int] | None = None  # None = fetch all players

    if not args.force and manifest.get("last_run"):
        last_run = datetime.fromisoformat(manifest["last_run"])
        last_fetch_type = manifest.get("fetch_type")
        if (last_run.date() == datetime.now(timezone.utc).date()
                and last_fetch_type not in ("blocked", "waiting", "none")):
            print(f"  Already fetched today ({last_fetch_type} at {last_run.strftime('%H:%M')} UTC) — skipping")
            set_github_outputs("", "none")
            return

    if args.force:
        print(f"  --force forcing full player fetch")
        fetch_type = "forced"

    elif not gw_finished:
        closure_gw = gw_number
        # ── Check if previous GW was not closed ───────────────
        if last_closed_gw < gw_number - 1:
            # Quick turnaround: previous GW finished but not yet recorded in manifest. Example:
            # | Day (1am CRON) | Matches yesterday      | current_gw | last_closed_gw | finished |
            # |----------------|------------------------|------------|----------------|----------|
            # | Thu            | GW10 Wed matches       | GW10       | 9              | false    |
            # | Fri            | GW10 Thu 8pm match     | GW10       | 9              | false    |
            # | Sat            | GW11 Fri 8pm match     | GW11       | 9              | false    |
            # on the Friday CRON the GW is not finished per the bootstrap, so "gw_closure" never triggers
            # ------------------------------------------------------------------------------------
            # checking if last_closed_gw is less than gw -1 triggers the "gw_closure"
            # fetch_type is set to "gw_closure" even though the current GW is also active —
            # this is intentional and has no downstream impact as gw_closure is informational.
            print(f"  GW{gw_number - 1} closed but not yet recorded — prioritising backfill closure fetch")
            fetch_type = "gw_closure"
            closure_gw = gw_number - 1
        else:
            fixtures_yesterday = get_fixtures_on_date(fixtures, target_date)
            if not fixtures_yesterday:
                print(f"  No matches on {target_date} — nothing to fetch")
                fetch_type = "none"
            else:
                team_ids = get_teams_played_in_gw(fixtures, gw_number)
                print(f"  {len(fixtures_yesterday)} match(es) on {target_date}:")
                for fix in fixtures_yesterday:
                        h = team_lookup.get(fix["team_h"], {}).get("short_name", "?")
                        a = team_lookup.get(fix["team_a"], {}).get("short_name", "?")
                        print(f"    {h} {fix['team_h_score']}-{fix['team_a_score']} {a}")
                print(f"  Fetching all teams that have played in GW{gw_number} so far ({len(team_ids)} teams)")
                fetch_type = "active_gw"


    elif not gw_data_checked:
        print(f"  GW{gw_number} finished but data_checked is False — waiting")
        fetch_type = "waiting"
    
    elif last_closed_gw < gw_number:
        print(f"  GW{gw_number} closed (finished + data_checked) — running full closure fetch")
        fetch_type = "gw_closure"
        closure_gw = gw_number
    
    else:
        print(f"  GW{gw_number} closure already recorded in manifest — nothing to fetch")
        fetch_type = "none"  # already closed

    # ── Early exit if nothing to fetch ────────────────────────
    if fetch_type in ("none", "waiting"):
        manifest.update({
            "season": args.season,
            "current_gw": gw_number,
            "fetch_type": fetch_type,
        })
        write_manifest(output, manifest)
        set_github_outputs(gw_number, fetch_type)
        print("\nDone!")
        return

    # ── Check event-status before fetching players ────────────
    print("\n[5/5] Fetching player data...")

    if not args.force:
        print("  Checking event-status...")
        ok, reason = check_event_status(session, target_date)
        if not ok:
            print(f"  BLOCKED: {reason}")
            print("  Workflow will retry at next scheduled run.")
            manifest.update({
                "season": args.season,
                "current_gw": gw_number,
                "fetch_type": "blocked",
                "blocked_reason": reason,
            })
            write_manifest(output, manifest)
            set_github_outputs(gw_number, "blocked")
            print("\nDone!")
            return
        print(f"  event-status OK: {reason}")

    # ── Fetch players ─────────────────────────────────────────
    players_dir.mkdir(parents=True, exist_ok=True)

    expected, fetched, failed_ids = fetch_players(
        elements, team_ids, players_dir, session, args.delay, args.dry_run
    )

    # ── GW extras ────────────────────────────────────────────
    gameweeks_dir = output / "gameweeks"

    if fetch_type == "forced":
        target_gw = gw_number if (gw_finished and gw_data_checked) else gw_number - 1
        if target_gw >= 1:
            finished_gws = [
                ev["id"] for ev in bootstrap.get("events", [])
                if ev.get("finished") and ev["id"] <= target_gw
            ]
            print(f"\n  Fetching GW extras for {len(finished_gws)} finished GW(s)...")
            for gw in finished_gws:
                fetch_gw_extras(gw, gameweeks_dir, session, args.dry_run)
        else:
            print("\n  No completed GW to fetch extras for — skipping")


    elif fetch_type == "gw_closure":
        print(f"\n  Fetching GW extras for GW{closure_gw}...")
        fetch_gw_extras(closure_gw, gameweeks_dir, session, args.dry_run)

    if fetch_type in ("gw_closure", "forced"):
        print(f"\n  Fetching season extras...")
        fetch_season_extras(output, args.season, session, args.dry_run)
    
    if args.dry_run:
        print("\nDone (dry run)!")
        return

    # ── Completion & manifest ─────────────────────────────────
    completed = len(failed_ids) == 0

    if fetch_type == "gw_closure" and completed:
        manifest["last_closed_gw"] = closure_gw
      
    elif fetch_type == "forced" and completed:
        manifest["last_closed_gw"] = gw_number if gw_finished else gw_number - 1

    manifest.update({
        "season": args.season,
        "current_gw": gw_number,
        "fetch_type": fetch_type,
        "expected_count": expected,
        "fetched_count": fetched,
        "failed_ids": failed_ids,
        "completed": completed,
    })
    write_manifest(output, manifest)

    # ── GitHub Actions output ─────────────────────────────────
    set_github_outputs(gw_number, fetch_type)

    print(f"\n{'='*60}")
    print(f"  Fetch complete — {fetch_type}")
    print(f"  Players: {fetched}/{expected}")
    if failed_ids:
        print(f"  Persistent failures: {len(failed_ids)} (recorded in manifest)")

    if not completed:
        raise SystemExit(1)

    print("\nDone!")


def main():
    parser = argparse.ArgumentParser(description=f"{cfg.LEAGUE_NAME} smart daily fetch script")
    parser.add_argument("--season", required=True, type=int,
                        help="Season start year (e.g. 2026)")
    parser.add_argument("--output", required=True,
                        help="Output directory (e.g. data/2026)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"Seconds between API requests (default {DEFAULT_DELAY})")
    parser.add_argument("--date",
                        help="Override target date YYYY-MM-DD (default: yesterday UTC)")
    parser.add_argument("--force", action="store_true",
                        help="Force a full player fetch")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — no files written, no player API calls")
    args = parser.parse_args()

    run(args)


if __name__ == "__main__":
    main()
