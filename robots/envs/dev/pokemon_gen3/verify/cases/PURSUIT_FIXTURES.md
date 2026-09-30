# Pursuit differential fixtures

All five teams pass pinned Showdown's `gen3ou` `TeamValidator`. Generation is
deterministic against clean revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`; the existing observation-only
patch was then used to confirm stable boundaries and labels.

| Case | Queue and result | Decision-boundary PRNG |
| --- | --- | --- |
| `pursuit-switch-survives` | switch 103 precedes move 200; intercepted Alakazam takes 206, Blissey enters, then takes 40 sand damage | `critical=6`, `damage_roll=8`, `quick_claw=0`; no accuracy draw |
| `pursuit-switch-ko-continues` | 1-HP Alakazam takes 1, faints, then the preselected Blissey enters | `critical=2`, `damage_roll=0`, `quick_claw=0`; no accuracy draw |
| `pursuit-gen3-paralysis-intercept` | turn 1 Thunder Wave precedes ordinary Pursuit; turn 2 switch 103 precedes the paralyzed user's move and interception KOs Alakazam | turn 1: `accuracy=33`, `setstatus_order=1`, `paralysis=3`, `accuracy=39`, `critical=13`, `damage_roll=6`, `quick_claw=3`; turn 2: `critical=6`, `damage_roll=5`, `quick_claw=2`, with **no paralysis or accuracy draw** |
| `pursuit-sleep-at-turn-start` | Spore leaves Tyranitar asleep; next turn Breloom switches before Tyranitar wakes, so normal 40-power Pursuit hits incoming Blissey for 34 | turn 1: `accuracy=68`, `setstatus_order=0`, `sleep_duration=0` (resolved duration 2), `quick_claw=3`; turn 2: `accuracy=49`, `critical=14`, `damage_roll=11`, `quick_claw=2` |
| `pursuit-no-switch-control` | Calm Mind then ordinary 40-power Pursuit; Alakazam takes 74 plus 15 sand | `accuracy=44`, `critical=9`, `damage_roll=5`, `quick_claw=1` |

Every initial boundary consumes one labeled `turn.quick_claw` draw. Exact seed
transitions, states, logs, and per-boundary draws are retained in
`derived/pursuit-oracle-expectations.json`.

The paralysis result corrects the initial spike hypothesis. Production tests
must follow the pinned oracle: Gen 3 interception does not make a second
paralysis check. No supported-feature classification follows from these oracle
fixtures alone.
