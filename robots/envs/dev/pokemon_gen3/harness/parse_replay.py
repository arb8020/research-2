#!/usr/bin/env python3
"""
Parse a Pokemon Showdown replay JSON (gen3ou or similar) into:
  - teams (species, revealed moves, items, abilities) per player
  - per-turn choices (move used or switch made) per player

Caveats (see README notes below / report):
  - Replay JSON has NO inputlog and NO explicit team list. Everything is
    reconstructed from the `log` field, so only what was actually revealed
    in battle is known (moves not used, held items not triggered, and
    abilities that never activated are invisible).
  - "Choice" reconstruction assumes each |move| or |switch| line immediately
    following a |turn| marker (before the next player's action) represents
    that player's action for the turn. Prior to Gen 3 replays there's no
    directly logged "the player chose to do X" separate from the resulting
    game event, so a forced action (e.g. a Pursuit-trapped switch, a
    faint-forced switch) can look identical to a voluntarily chosen switch.
    We flag these heuristically.
"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict


def load_replay(path):
    with open(path) as f:
        return json.load(f)


def parse_log(log_text):
    """Walk the log, tracking per-turn events, nickname->species map, and
    revealed team info."""
    lines = log_text.split("\n")

    teams = {
        "p1": {},  # nickname -> {species, moves:set, item, ability, gender}
        "p2": {},
    }
    turns = defaultdict(lambda: defaultdict(list))  # turn -> player -> [events]
    current_turn = 0
    players = {}

    def side_of(tag):
        # tag like "p1a: Nickname"
        return tag[:2]

    def nick_of(tag):
        return tag.split(": ", 1)[1] if ": " in tag else tag

    for line in lines:
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        cmd = parts[1] if len(parts) > 1 else ""

        if cmd == "player" and len(parts) >= 4 and parts[3]:
            players[parts[2]] = parts[3]

        elif cmd == "turn":
            current_turn = int(parts[2])

        elif cmd == "switch" or cmd == "drag":
            side = side_of(parts[2])
            nick = nick_of(parts[2])
            species_full = parts[3]  # "Medicham, M" etc
            species = species_full.split(",")[0].strip()
            team = teams[side]
            if nick not in team:
                team[nick] = {
                    "species": species,
                    "moves": set(),
                    "item": None,
                    "ability": None,
                }
            turns[current_turn][side].append(
                {"type": "switch", "target": species, "forced": cmd == "drag"}
            )

        elif cmd == "move":
            side = side_of(parts[2])
            nick = nick_of(parts[2])
            move_name = parts[3]
            team = teams[side]
            if nick in team:
                team[nick]["moves"].add(move_name)
            turns[current_turn][side].append({"type": "move", "move": move_name})

        elif cmd == "-item" or cmd == "-enditem":
            # reveals held item, e.g. |-item|p1a: X|Leftovers
            side = side_of(parts[2])
            nick = nick_of(parts[2])
            item = parts[3]
            if nick in teams[side]:
                teams[side][nick]["item"] = item

        elif cmd == "-ability":
            side = side_of(parts[2])
            nick = nick_of(parts[2])
            ability = parts[3]
            if nick in teams[side]:
                teams[side][nick]["ability"] = ability

        elif cmd == "-heal" and "[from] item:" in line:
            # e.g. |-heal|p1a: X|21/100|[from] item: Leftovers
            side = side_of(parts[2])
            nick = nick_of(parts[2])
            m = re.search(r"\[from\] item: (.+)", line)
            if m and nick in teams[side]:
                teams[side][nick]["item"] = m.group(1)

    return players, teams, turns


def summarize(players, teams, turns):
    out = {"players": players, "teams": {}, "turns": {}}
    for side, team in teams.items():
        out["teams"][side] = {}
        for nick, info in team.items():
            out["teams"][side][nick] = {
                "species": info["species"],
                "moves": sorted(info["moves"]),
                "item": info["item"],
                "ability": info["ability"],
            }
    for t in sorted(turns.keys()):
        out["turns"][t] = {side: evs for side, evs in turns[t].items()}
    return out


def main():
    path = Path(__file__).parent / "sample_replay.json"
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])

    replay = load_replay(path)
    players, teams, turns = parse_log(replay["log"])
    result = summarize(players, teams, turns)

    print("=== PLAYERS ===")
    print(json.dumps(result["players"], indent=2))

    print("\n=== TEAMS (as revealed in battle) ===")
    print(json.dumps(result["teams"], indent=2))

    print("\n=== PER-TURN CHOICES ===")
    for t, sides in result["turns"].items():
        print(f"Turn {t}:")
        for side, events in sides.items():
            for ev in events:
                if ev["type"] == "move":
                    print(f"  {side}: used {ev['move']}")
                else:
                    forced_tag = " (forced/drag)" if ev.get("forced") else ""
                    print(f"  {side}: switched to {ev['target']}{forced_tag}")

    print(
        "\nNOTE: only species/moves/items/abilities actually revealed in the "
        "log are known. Unrevealed party members, unused moves, and "
        "non-triggering items/abilities are NOT present. Forced switches "
        "(post-faint) vs voluntary switches are not distinguishable from "
        "the log alone without cross-referencing |faint| on the prior line."
    )


if __name__ == "__main__":
    main()
