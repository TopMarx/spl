"""
Fantasy CSV Generator (league-agnostic)

Generates CSV files from fetched fantasy API JSON data. File prefixes come
from league_config.py ({slug}); ID columns use generic names: player_id /
opta_id (the API's per-season `id` / stable Opta `code`), team_id /
team_opta_id, fixture_id / fixture_opta_id.

Reads from:
  data/{season}/{slug}-bootstrap_{season}.json
  data/{season}/{slug}-fixtures_{season}.json
  data/{season}/gameweeks/gw{N}/live.json
  data/{season}/gameweeks/gw{N}/dream-team.json
  data/{season}/{slug}-dream-team_{season}.json
  data/{season}/{slug}-set-piece-notes_{season}.json
  data/{season}/{slug}-regions_{season}.json

Writes to:
  data/{season}/csv/players.csv
  data/{season}/csv/teams.csv
  data/{season}/csv/fixtures.csv
  data/{season}/csv/gameweeks.csv
  data/{season}/csv/live.csv
  data/{season}/csv/dream-teams.csv
  data/{season}/csv/set-piece-notes.csv
  data/{season}/csv/regions.csv
  data/{season}/csv/players/history/{player_id}_{first}_{second}_{opta_id}.csv
  data/{season}/csv/players/history_past/{player_id}_{first}_{second}_{opta_id}.csv

Usage:
  python3 scripts/generate_csv.py --season 2026
  python3 scripts/generate_csv.py --season 2026 --output data/2026
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import league_config as cfg

SLUG = cfg.LEAGUE_SLUG


# ─── Helpers ──────────────────────────────────────────────────

def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        print(f"  WARNING: {path} not found, skipping")
        return None
    with open(path) as f:
        return json.load(f)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def player_display_name(el: dict) -> str:
    known = el.get("known_name", "")
    if known:
        return known
    first = el.get("first_name", "")
    second = el.get("second_name", "")
    return f"{first} {second}".strip()


# ─── Generators ───────────────────────────────────────────────

def generate_players(bootstrap: dict, team_lookup: dict, csv_dir: Path) -> None:
    """Generate players.csv from bootstrap elements."""
    fieldnames = [
        "player_id", "opta_id", "first_name", "second_name", "web_name", "known_name",
        "team_id", "team_opta_id", "team_name", "team_short_name", "element_type",
        "position", "status", "news",
        *cfg.STAT_FIELDS,
        "now_cost", "selected_by_percent",
    ]

    position_map = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD", 5: "MGR"}

    rows = []
    for el in bootstrap.get("elements", []):
        teamup = team_lookup.get(el.get("team"), {})
        rows.append({
            "player_id": el.get("id"),
            "opta_id": el.get("code"),
            "first_name": el.get("first_name"),
            "second_name": el.get("second_name"),
            "web_name": el.get("web_name"),
            "known_name": el.get("known_name") or "",
            "team_id": el.get("team"),
            "team_opta_id": el.get("team_code"),
            "team_name": teamup.get("name"),
            "team_short_name": teamup.get("short_name"),
            "element_type": el.get("element_type"),
            "position": position_map.get(el.get("element_type", 0), ""),
            "status": el.get("status"),
            "news": el.get("news") or "",
            **{k: el.get(k, 0) for k in cfg.STAT_FIELDS},
            "now_cost": el.get("now_cost"),
            "selected_by_percent": el.get("selected_by_percent"),
        })

    count = write_csv(csv_dir / "players.csv", rows, fieldnames)
    print(f"  → players.csv ({count} rows)")


def generate_teams(bootstrap: dict, csv_dir: Path) -> None:
    """Generate teams.csv from bootstrap teams."""
    fieldnames = [
        "team_id", "team_opta_id", "name", "short_name",
        "strength", "strength_overall_home", "strength_overall_away",
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away",
    ]

    rows = []
    for t in bootstrap.get("teams", []):
        rows.append({
            "team_id": t.get("id"),
            "team_opta_id": t.get("code"),
            "name": t.get("name"),
            "short_name": t.get("short_name"),
            "strength": t.get("strength"),
            "strength_overall_home": t.get("strength_overall_home"),
            "strength_overall_away": t.get("strength_overall_away"),
            "strength_attack_home": t.get("strength_attack_home"),
            "strength_attack_away": t.get("strength_attack_away"),
            "strength_defence_home": t.get("strength_defence_home"),
            "strength_defence_away": t.get("strength_defence_away"),
        })

    count = write_csv(csv_dir / "teams.csv", rows, fieldnames)
    print(f"  → teams.csv ({count} rows)")


def generate_gameweeks(bootstrap: dict, csv_dir: Path) -> None:
    """Generate gameweeks.csv from bootstrap events."""
    fieldnames = [
        "id", "name", "deadline_time",
        "average_entry_score", "highest_score",
        "finished", "data_checked",
        "is_previous", "is_current", "is_next",
    ]

    rows = []
    for ev in bootstrap.get("events", []):
        rows.append({
            "id": ev.get("id"),
            "name": ev.get("name"),
            "deadline_time": ev.get("deadline_time"),
            "average_entry_score": ev.get("average_entry_score"),
            "highest_score": ev.get("highest_score"),
            "finished": ev.get("finished"),
            "data_checked": ev.get("data_checked"),
            "is_previous": ev.get("is_previous"),
            "is_current": ev.get("is_current"),
            "is_next": ev.get("is_next"),
        })

    count = write_csv(csv_dir / "gameweeks.csv", rows, fieldnames)
    print(f"  → gameweeks.csv ({count} rows)")


def generate_fixtures(fixtures: list, team_lookup: dict, csv_dir: Path) -> None:
    """Generate fixtures.csv from fixtures data."""
    fieldnames = [
        "fixture_id", "fixture_opta_id", "gameweek",
        "team_h_id", "team_h_opta_id",
        "team_h_name", "team_h_short_name",
        "team_a_id", "team_a_opta_id",
        "team_a_name", "team_a_short_name",
        "team_h_score", "team_a_score",
        "kickoff_time", "finished", "started",
        "team_h_difficulty", "team_a_difficulty",
    ]

    rows = []
    for fix in fixtures:
        rows.append({
            "fixture_id": fix.get("id"),
            "fixture_opta_id": fix.get("code"),
            "gameweek": fix.get("event"),
            "team_h_id": fix.get("team_h"),
            "team_h_opta_id": team_lookup.get(fix.get("team_h"), {}).get("code"),
            "team_h_name": team_lookup.get(fix.get("team_h"), {}).get("name"),
            "team_h_short_name": team_lookup.get(fix.get("team_h"), {}).get("short_name"),
            "team_a_id": fix.get("team_a"),
            "team_a_opta_id": team_lookup.get(fix.get("team_a"), {}).get("code"),
            "team_a_name": team_lookup.get(fix.get("team_a"), {}).get("name"),
            "team_a_short_name": team_lookup.get(fix.get("team_a"), {}).get("short_name"),
            "team_h_score": fix.get("team_h_score"),
            "team_a_score": fix.get("team_a_score"),
            "kickoff_time": fix.get("kickoff_time"),
            "finished": fix.get("finished"),
            "started": fix.get("started"),
            "team_h_difficulty": fix.get("team_h_difficulty"),
            "team_a_difficulty": fix.get("team_a_difficulty"),
        })

    count = write_csv(csv_dir / "fixtures.csv", rows, fieldnames)
    print(f"  → fixtures.csv ({count} rows)")


def generate_live(gameweeks_dir: Path, csv_dir: Path) -> None:
    """Generate live.csv from gameweeks/gw{N}/live.json files."""
    fieldnames = [
        "gw", "player_id",
        *cfg.STAT_FIELDS,
        "played", "in_dreamteam",
    ]

    rows = []
    for gw_dir in sorted(gameweeks_dir.glob("gw*")):
        live_path = gw_dir / "live.json"
        live = load_json(live_path)
        if not isinstance(live, dict):
            continue
        try:
            gw = int(gw_dir.name[2:])
        except ValueError:
            continue
        for el in live.get("elements", []):
            stats = el.get("stats", {})
            rows.append({
                "gw": gw,
                "player_id": el.get("id"),
                **{k: stats.get(k, 0) for k in cfg.STAT_FIELDS},
                "played": stats.get("played", ""),
                "in_dreamteam": stats.get("in_dreamteam", False),
            })

    count = write_csv(csv_dir / "live.csv", rows, fieldnames)
    print(f"  → live.csv ({count} rows)")


def generate_dream_teams(
    gameweeks_dir: Path, season_dream_team: dict | None,
    element_lookup: dict, csv_dir: Path
) -> None:
    """Generate dream-teams.csv from per-GW and season dream team data."""
    fieldnames = [
        "type", "gw", "position", "player_id", "opta_id", "name",
        "player_position", "points", "is_top_player",
    ]

    position_map = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    rows = []

    def dream_team_rows(data: dict, type_: str, gw: int | str) -> list[dict]:
        top_player_id = data.get("top_player", {}).get("id")
        result = []
        for entry in data.get("team", []):
            player_id = entry.get("element")
            el = element_lookup.get(player_id, {})
            result.append({
                "type": type_,
                "gw": gw,
                "position": entry.get("position"),
                "player_id": player_id,
                "opta_id": el.get("code"),
                "name": player_display_name(el),
                "player_position": position_map.get(el.get("element_type", 0), ""),
                "points": entry.get("points"),
                "is_top_player": player_id == top_player_id,
            })
        return result

    for gw_dir in sorted(gameweeks_dir.glob("gw*")):
        dt_path = gw_dir / "dream-team.json"
        data = load_json(dt_path)
        if not isinstance(data, dict):
            continue
        try:
            gw = int(gw_dir.name[2:])
        except ValueError:
            continue
        rows.extend(dream_team_rows(data, "gw", gw))

    if season_dream_team:
        rows.extend(dream_team_rows(season_dream_team, "season", ""))

    count = write_csv(csv_dir / "dream-teams.csv", rows, fieldnames)
    print(f"  → dream-teams.csv ({count} rows)")


def generate_regions(regions_data: list, csv_dir: Path) -> None:
    """Generate regions.csv from regions data."""
    fieldnames = ["id", "name", "code", "iso_code_short", "iso_code_long"]

    rows = []
    for region in regions_data:
        rows.append({
            "id": region.get("id"),
            "name": region.get("name"),
            "code": region.get("code"),
            "iso_code_short": region.get("iso_code_short", ""),
            "iso_code_long": region.get("iso_code_long", ""),
        })

    count = write_csv(csv_dir / "regions.csv", rows, fieldnames)
    print(f"  → regions.csv ({count} rows)")


def generate_set_piece_notes(set_piece_data: dict, team_lookup: dict, csv_dir: Path) -> None:
    """Generate set-piece-notes.csv from set piece taker notes."""
    fieldnames = [
        "team_id", "team_opta_id", "team_name", "team_short_name",
        "note_index", "info_message", "source_link", "external_link", "last_updated",
    ]

    last_updated = set_piece_data.get("last_updated", "")

    rows = []
    for entry in set_piece_data.get("teams", []):
        team_id = entry.get("id")
        team = team_lookup.get(team_id, {})
        for i, note in enumerate(entry.get("notes", [])):
            rows.append({
                "team_id": team_id,
                "team_opta_id": team.get("code"),
                "team_name": team.get("name"),
                "team_short_name": team.get("short_name"),
                "note_index": i + 1,
                "info_message": note.get("info_message", ""),
                "source_link": note.get("source_link", ""),
                "external_link": note.get("external_link", False),
                "last_updated": last_updated,
            })

    count = write_csv(csv_dir / "set-piece-notes.csv", rows, fieldnames)
    print(f"  → set-piece-notes.csv ({count} rows)")


def generate_player_csvs(players_dir: Path, team_lookup: dict, csv_dir: Path) -> None:
    """Generate per-player history and history_past CSVs from player JSON files.

    Output:
      csv/players/history/{player_id}_{first}_{second}_{opta_id}.csv
      csv/players/history_past/{player_id}_{first}_{second}_{opta_id}.csv

    Filename is taken directly from the JSON stem so it always reflects the
    player's current name (fetch.py guarantees this). Before writing, stale
    CSVs are removed via {player_id}_*.csv glob — the same approach fetch.py
    uses for JSON files, ensuring renames and known_name changes stay in sync.

    history_past is skipped if the array is empty (new players with no prior
    seasons).
    """
    player_files = sorted(players_dir.glob("*.json"))
    if not player_files:
        print("  SKIP: player CSVs (no player JSON files found)")
        return

    history_dir = csv_dir / "players" / "history"
    history_past_dir = csv_dir / "players" / "history_past"

    history_fieldnames = [
        "player_id", "fixture_id", "gameweek", "kickoff_time", "was_home",
        "opponent_team_id", "opponent_team_name",
        "team_h_score", "team_a_score", "modified",
        *cfg.STAT_FIELDS,
        "value", "selected", "transfers_in", "transfers_out", "transfers_balance",
    ]

    history_past_fieldnames = [
        "player_id", "opta_id", "season_name",
        "start_cost", "end_cost",
        *cfg.STAT_FIELDS,
    ]

    history_count = 0
    history_past_count = 0

    for json_path in player_files:
        stem = json_path.stem  # e.g. "442_Mohamed_Salah_56322"
        player_id = int(stem.split("_")[0])
        csv_name = stem + ".csv"

        data = load_json(json_path)
        if not isinstance(data, dict):
            continue

        # Remove stale CSVs for this player before writing — mirrors the
        # glob-and-unlink pattern in fetch.py's fetch_player(), ensuring that
        # name changes (including known_name updates) don't leave orphaned files.
        for old_file in history_dir.glob(f"{player_id}_*.csv"):
            old_file.unlink()
        for old_file in history_past_dir.glob(f"{player_id}_*.csv"):
            old_file.unlink()

        # ── history (current season, one row per match) ───────
        history_rows = []
        for match in data.get("history", []):
            opponent_team_id = match.get("opponent_team")
            history_rows.append({
                "player_id": match.get("element"),
                "fixture_id": match.get("fixture"),
                "gameweek": match.get("round"),
                "kickoff_time": match.get("kickoff_time"),
                "was_home": match.get("was_home"),
                "opponent_team_id": opponent_team_id,
                "opponent_team_name": team_lookup.get(opponent_team_id, {}).get("name"),
                "team_h_score": match.get("team_h_score"),
                "team_a_score": match.get("team_a_score"),
                "modified": match.get("modified"),
                **{k: match.get(k, 0) for k in cfg.STAT_FIELDS},
                "value": match.get("value"),
                "selected": match.get("selected"),
                "transfers_in": match.get("transfers_in", 0),
                "transfers_out": match.get("transfers_out", 0),
                "transfers_balance": match.get("transfers_balance", 0),
            })
        write_csv(history_dir / csv_name, history_rows, history_fieldnames)
        history_count += 1

        # ── history_past (one row per past season) ────────────
        history_past = data.get("history_past", [])
        if history_past:
            past_rows = []
            for season in history_past:
                past_rows.append({
                    "player_id": player_id,
                    "opta_id": season.get("element_code"),
                    "season_name": season.get("season_name"),
                    "start_cost": season.get("start_cost"),
                    "end_cost": season.get("end_cost"),
                    **{k: season.get(k, 0) for k in cfg.STAT_FIELDS},
                })
            write_csv(history_past_dir / csv_name, past_rows, history_past_fieldnames)
            history_past_count += 1

    print(f"  → players/history/ ({history_count} files)")
    print(f"  → players/history_past/ ({history_past_count} files)")


# ─── Main ─────────────────────────────────────────────────────

def run(args):
    output = Path(args.output)
    csv_dir = output / "csv"

    print(f"{cfg.LEAGUE_NAME} CSV Generator — Season {cfg.season_label(args.season)}")
    print(f"Source: {output}")
    print(f"Output: {csv_dir}")
    print("=" * 60)

    bootstrap_path = output / f"{SLUG}-bootstrap_{args.season}.json"
    fixtures_path = output / f"{SLUG}-fixtures_{args.season}.json"

    bootstrap = load_json(bootstrap_path)
    fixtures = load_json(fixtures_path)

    if not isinstance(bootstrap, dict):
        print("FATAL: Bootstrap data not found or invalid. Run fetch.py first.")
        raise SystemExit(1)

    team_lookup = {t["id"]: t for t in bootstrap.get("teams", [])}
    element_lookup = {el["id"]: el for el in bootstrap.get("elements", [])}

    print("\nGenerating CSVs...")
    generate_players(bootstrap, team_lookup, csv_dir)
    generate_teams(bootstrap, csv_dir)
    generate_gameweeks(bootstrap, csv_dir)

    if not isinstance(fixtures, list):
        print("  SKIP: fixtures.csv (fixtures data not found or invalid)")
    else:
        generate_fixtures(fixtures, team_lookup, csv_dir)

    gameweeks_dir = output / "gameweeks"

    if gameweeks_dir.exists():
        generate_live(gameweeks_dir, csv_dir)
        season_dream_team = load_json(output / f"{SLUG}-dream-team_{args.season}.json")
        if not isinstance(season_dream_team, dict):
            season_dream_team = None
        generate_dream_teams(gameweeks_dir, season_dream_team, element_lookup, csv_dir)
    else:
        print("  SKIP: live.csv and dream-teams.csv (no gameweeks directory)")

    players_dir = output / "players"
    if players_dir.exists():
        generate_player_csvs(players_dir, team_lookup, csv_dir)
    else:
        print("  SKIP: player CSVs (no players directory)")

    set_piece_path = output / f"{SLUG}-set-piece-notes_{args.season}.json"
    set_piece_data = load_json(set_piece_path)
    if isinstance(set_piece_data, dict):
        generate_set_piece_notes(set_piece_data, team_lookup, csv_dir)
    else:
        print("  SKIP: set-piece-notes.csv (data not found)")

    regions_path = output / f"{SLUG}-regions_{args.season}.json"
    regions_data = load_json(regions_path)
    if isinstance(regions_data, list):
        generate_regions(regions_data, csv_dir)
    else:
        print("  SKIP: regions.csv (data not found)")

    print("\nDone!")


def main():
    parser = argparse.ArgumentParser(description=f"Generate CSV files from {cfg.LEAGUE_NAME} JSON data")
    parser.add_argument("--season", required=True, type=int,
                        help="Season start year (e.g. 2026)")
    parser.add_argument("--output", default=None,
                        help="Data directory (default: data/{season})")
    args = parser.parse_args()

    args.output = args.output or f"data/{args.season}"
    run(args)


if __name__ == "__main__":
    main()
