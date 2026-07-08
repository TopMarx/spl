"""
Fantasy Latest Generator (league-agnostic)

Generates the latest/ directory from the current season's fetched data.
The latest/ directory provides a stable location for consumers who always
want the most recent data without knowing the current season year.
File prefixes come from league_config.py ({slug}).

Reads from:
  data/{season}/{slug}-bootstrap_{season}.json
  data/{season}/{slug}-fixtures_{season}.json
  data/{season}/fetch-manifest.json
  data/{season}/players/{player_id}_{first}_{second}_{opta_id}.json

Writes to:
  latest/{slug}-bootstrap.json
  latest/{slug}-fixtures.json
  latest/fetch-manifest.json
  latest/players-{team_opta_id}.json      — one file per team, current season
                                          history only, all players on that team

Player file format:
  {
    "team_opta_id": 43,
    "team_name": "Example FC",
    "generated_at": "2026-07-08T01:23:45Z",
    "players": [
      {
        "player_id": 123,
        "opta_id": 456789,
        "first_name": "...",
        "second_name": "...",
        "web_name": "...",
        "position": "MID",
        "history": [...]
      }
    ]
  }

Usage:
  python3 scripts/generate_latest.py --season 2026
  python3 scripts/generate_latest.py --season 2026 --data data/2026 --output latest
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import league_config as cfg

SLUG = cfg.LEAGUE_SLUG

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD", 5: "MGR"}


# ─── Helpers ──────────────────────────────────────────────────

def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        print(f"  WARNING: {path} not found, skipping")
        return None
    with open(path) as f:
        return json.load(f)


def write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── Main ─────────────────────────────────────────────────────

def run(args):
    data_dir = Path(args.data)
    latest_dir = Path(args.output)
    generated_at = datetime.now(timezone.utc).isoformat()

    print(f"{cfg.LEAGUE_NAME} Latest Generator — Season {cfg.season_label(args.season)}")
    print(f"Source: {data_dir}")
    print(f"Output: {latest_dir}")
    print("=" * 60)

    # ── Load source data ──────────────────────────────────────
    bootstrap = load_json(data_dir / f"{SLUG}-bootstrap_{args.season}.json")
    fixtures = load_json(data_dir / f"{SLUG}-fixtures_{args.season}.json")
    manifest = load_json(data_dir / "fetch-manifest.json")

    if not isinstance(bootstrap, dict):
        print("FATAL: Bootstrap data not found or invalid. Run fetch.py first.")
        raise SystemExit(1)

    players_dir = data_dir / "players"
    if not players_dir.exists():
        print("FATAL: Players directory not found. Run fetch.py first.")
        raise SystemExit(1)

    latest_dir.mkdir(parents=True, exist_ok=True)

    # ── Build lookups from bootstrap ──────────────────────────
    # team id → {code, name}
    team_lookup: dict[int, dict] = {}
    for t in bootstrap.get("teams", []):
        team_lookup[t["id"]] = {
            "code": t["code"],
            "name": t["name"],
        }

    # element id → element dict
    element_lookup: dict[int, dict] = {}
    for el in bootstrap.get("elements", []):
        element_lookup[el["id"]] = el

    # ── Copy bootstrap ────────────────────────────────────────
    write_json(latest_dir / f"{SLUG}-bootstrap.json", bootstrap)
    print(f"\n  → {SLUG}-bootstrap.json")

    # ── Copy fixtures ─────────────────────────────────────────
    if fixtures:
        write_json(latest_dir / f"{SLUG}-fixtures.json", fixtures)
        print(f"  → {SLUG}-fixtures.json")

    # ── Copy manifest ─────────────────────────────────────────
    if manifest:
        write_json(latest_dir / "fetch-manifest.json", manifest)
        print(f"  → fetch-manifest.json")

    # ── Determine whether to regenerate history_past ──────────
    # history_past is essentially static within a season, so we only
    # regenerate it on full player fetches (GW closure / forced) or
    # when the target file doesn't exist yet.
    fetch_type = manifest.get("fetch_type") if isinstance(manifest, dict) else None
    history_past_path = latest_dir / "players-history-past.json"
    write_history_past = (
        fetch_type in ("gw_closure", "forced")
        or not history_past_path.exists()
    )

    # ── Build per-team player files ───────────────────────────
    print(f"\n  Building per-team player files from {players_dir}/...")

    # Group player files by team code
    team_players: dict[int, list[dict]] = {}
    all_history_past: list[dict] = []

    player_files = list(players_dir.glob("*.json"))
    print(f"  Found {len(player_files)} player file(s)")

    for player_file in player_files:
        # Parse player_id from filename: {player_id}_{first}_{second}_{opta_id}.json
        parts = player_file.stem.split("_")
        if len(parts) < 2:
            print(f"  SKIP: unexpected filename {player_file.name}")
            continue

        try:
            player_id = int(parts[0])
        except ValueError:
            print(f"  SKIP: cannot parse player ID from {player_file.name}")
            continue

        el = element_lookup.get(player_id)
        if not el:
            print(f"  SKIP: player ID {player_id} not found in bootstrap")
            continue

        team_id = el.get("team")
        if not isinstance(team_id, int):
            print(f"  SKIP: player ID {player_id} has no valid team ID")
            continue
        team_info = team_lookup.get(team_id)
        if not team_info:
            print(f"  SKIP: team ID {team_id} not found in bootstrap")
            continue

        team_opta_id = team_info["code"]

        # Load player file and extract current season history only
        player_data = load_json(player_file)
        if not isinstance(player_data, dict):
            continue

        player_entry = {
            "player_id": player_id,
            "opta_id": el.get("code"),
            "first_name": el.get("first_name"),
            "second_name": el.get("second_name"),
            "web_name": el.get("web_name"),
            "known_name": el.get("known_name") or "",
            "position": POSITION_MAP.get(el.get("element_type", 0), ""),
            "history": player_data.get("history", []),
        }

        # Collect history_past entry if regenerating and player has prior seasons
        if write_history_past and player_data.get("history_past"):
            all_history_past.append({
                "player_id": player_id,
                "opta_id": el.get("code"),
                "first_name": el.get("first_name"),
                "second_name": el.get("second_name"),
                "web_name": el.get("web_name"),
                "known_name": el.get("known_name") or "",
                "position": POSITION_MAP.get(el.get("element_type", 0), ""),
                "history_past": player_data["history_past"],
            })

        if team_opta_id not in team_players:
            team_players[team_opta_id] = []
        team_players[team_opta_id].append(player_entry)

    # Write one file per team
    for team_opta_id, players in sorted(team_players.items()):
        team_id = next(
            (tid for tid, info in team_lookup.items() if info["code"] == team_opta_id),
            None
        )
        team_name = team_lookup.get(team_id, {}).get("name", "") if team_id else ""

        output_data = {
            "team_opta_id": team_opta_id,
            "team_name": team_name,
            "season": args.season,
            "generated_at": generated_at,
            "players": sorted(players, key=lambda p: p["second_name"]),
        }

        filename = f"players-{team_opta_id}.json"
        write_json(latest_dir / filename, output_data)
        print(f"  → {filename} ({len(players)} players)")

    print(f"\n  {len(team_players)} team file(s) written to {latest_dir}/")

    # ── Write combined history_past file ──────────────────────
    if write_history_past:
        write_json(history_past_path, {
            "season": args.season,
            "generated_at": generated_at,
            "players": sorted(all_history_past, key=lambda p: p["second_name"]),
        })
        print(f"\n  → players-history-past.json ({len(all_history_past)} players)")
    else:
        print(f"\n  → players-history-past.json (skipped — regenerated on GW closure/force only)")

    print("\nDone!")


def main():
    parser = argparse.ArgumentParser(
        description=f"Generate latest/ directory from current season {cfg.LEAGUE_NAME} data"
    )
    parser.add_argument("--season", required=True, type=int,
                        help="Season start year (e.g. 2026)")
    parser.add_argument("--data", default=None,
                        help="Source data directory (default: data/{season})")
    parser.add_argument("--output", default="latest",
                        help="Output directory (default: latest)")
    args = parser.parse_args()

    args.data = args.data or f"data/{args.season}"
    run(args)


if __name__ == "__main__":
    main()
