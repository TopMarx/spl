"""
League configuration — the only file that differs between league repos.

All scripts import their league-specific values from here, so the rest of
the codebase stays byte-identical across every league repo. To port a fix,
copy the other scripts verbatim.

SEASON_CONVENTION:
  "cross_year"    — season spans two calendar years (Aug–May, like FPL).
                    Season label is the start year; a first-GW deadline in
                    Jul–Dec belongs to a season starting that year, Jan–Jun
                    to the season that started the previous year.
  "calendar_year" — season fits one calendar year (spring–autumn, e.g.
                    Eliteserien, Allsvenskan). Season label is simply the
                    year of the first GW deadline.
"""

# Short lowercase identifier — used as the file prefix (e.g. "{slug}-bootstrap_2026.json")
LEAGUE_SLUG = "spl"

# Human-readable name for logs and README
LEAGUE_NAME = "Fantasy Saudi Pro League"

# API base URL, no trailing slash
API_BASE = "https://en.fantasy.spl.com.sa/api"

# "cross_year" or "calendar_year" — see module docstring
SEASON_CONVENTION = "cross_year"

# element_type ID to exclude from player fetches (FPL uses 5 for managers).
# None = fetch every element in the bootstrap.
MANAGER_ELEMENT_TYPE = None

# User-Agent header sent with every request
USER_AGENT = f"{LEAGUE_SLUG}-data/1.0"

# Ordered stat columns for this league's CSVs (players.csv, live.csv, and the
# per-player history/history_past CSVs). The first twelve are common to every
# league on this platform; the rest are league-specific metrics, verified
# against the league's live API. Raw JSON always keeps every field regardless
# of this list — this only controls CSV columns. Missing keys default to 0.
STAT_FIELDS = [
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "bonus",
    "fmmp",
    "winning_goals",
    "won_tackle",
    "accurate_pass",
    "clearances_blocks_interceptions",
    "shot_target",
    "big_chance_created",
    "big_chance_missed",
    "performance_index",
    "total_points",
]


def season_label(season: int) -> str:
    """Human-readable season label: '2025/26' for cross-year, '2026' for calendar-year."""
    if SEASON_CONVENTION == "calendar_year":
        return str(season)
    return f"{season}/{str(season + 1)[-2:]}"
