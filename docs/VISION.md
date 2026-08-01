# Mimir: vision & wish-list

Pre-wayfinding capture (2026-07-31). This is the raw "list of things we want" plus the
decisions already made, so charting sessions don't re-litigate. The wayfinder map, once
charted, is the live document; this file is its context anchor.

## Thesis

Working on a codebase should feel like playing a good open-world game / RTS. Today,
issues, worktrees, branches, PRs, and agent sessions all feel divorced from the code
they're about. The code (the git DAG) is the substrate everyone agrees on — it's a
*location, a map* — and the facts about pending work should be joined to it spatially.

The historically unsolved part — keeping an intent↔code join fresh — failed because the
maintenance loop required continuous human judgment nobody would pay for (tickgit,
todocheck, Palantír, Crystal: all validated, all dead). **Agents change the economics**:
they are both the main consumer of the join and its repair crew. That is the bet.

## Three layers

1. **Code / terrain** — mimir. Facts derived from the working tree + git + declared
   tracker: health, maturity, quests, who-is-where.
2. **Sessions / conversations** — obol. Agent lifecycle, transcripts, dispatch,
   channels. Source of truth for conversations.
3. **Work management** — the join (markers, trailers, worktree identity) + the
   external tracker (lifecycle, priority, discussion).

Custody by competence, everywhere: lifecycle lives in the tracker, location lives in
the code, conversations live in obol, and **mimir writes to none of them** — it is the
read-only mirror that notices when sides disagree. No sync engines (provably cursed:
round-trip engineering, git-bug bridges), no tracker replacement (network-effect wall:
Fossil). The durable niche is the position no tracker vendor can occupy (local working
tree) and no linter wants (network state).

## Principles (settled)

- **CLI-first gravity**: code we use and gradually use more of → gravity for users.
  A feature enters mimir only after we've done it manually and wanted it again.
- **Continuous granularity** (Casey): raw git/gh → mimir primitives (`--json`) →
  composed views (sections, check) → surfaces (web). No level may hide the one below;
  every higher call trivially decomposable into lower ones.
- **Stateless recomputation**: no `.mimir/`, no snapshots. Watermarks already exist
  (git blame time vs issue `updatedAt`). Rerunning can't go stale.
- **Read-only forever**: an apply-mode would be a sibling verb, never a flag.
- **Sections, not subcommands**; multi-target args, not group-by flags.
- **Honest degradation**: `IssueState = Open | Closed | Unknown(reason)`; offline
  never fails CI; inferred joins labeled inferred, never blended with structural ones.
- **Easy exit**: quitting mimir = stop running a CLI. Markers left behind are plain
  valid TODOs.

## Built (on main)

- `mimir scan` — structure/heat/surface/rot/todo, validated on obol; rot skips
  interface stubs; erosion global scalar is *shaky* (concentration-sensitive, anchors
  unvalidated) — demote to per-zone comparative + top-mass-holders before README.
- `mimir quests` — turn-in section: merged/content-merged verdict chain, revert
  detection (positive evidence only), triage for dirty-done worktrees, age + upstream
  state, paste-able remedies. In real use on obol (reaped 14 worktrees; refills daily).
- 24 matklad-style boundary tests (fixture repo → real CLI `--json` → assert on data).
- Parked: `server-ui` branch (canvas, CodeMirror+vim, overlays, session mining).

## Wish-list (decided designs, unbuilt — rough build order)

1. **Active quests**: live branches clustered into *efforts* by diff overlap (stacks
   and v2/v3 retries collapse), 14d recency window, ⚑ = worktree checked out,
   dominant-dir location, zone-scoped `mimir quests <path>`. Unit is the effort, not
   the branch. Scratch dirs excluded.
2. **`--at file:line[-line]`** — likely FIRST build: hunk-interval index over live
   branches → "who's here?" + teleport target (worktree path + mapped line, via
   $EDITOR). Palantír/Crystal reborn; no shipping competitor. Pure CLI, no surface
   needed: view via `hunk` (ext/hunk — terminal diff viewer on OpenTUI +
   @pierre/diffs, MIT, inline agent annotations + watch mode; later ticket: emit
   hunk-renderable annotations = NPC symbols in the terminal). Editor integration =
   a keybind calling --at at cursor. Subset of active-quests machinery; active
   inherits its plumbing. Z-axis expansion is its eventual web UI.
3. **Pinned + check**: `TODO(#N)` markers as foreign keys (code owns location).
   Tracker declared once (config or origin inference), refs normalized at boundary
   into a sum type. gh-only v1. `mimir check` in CI: hard-fail marker→closed/missing
   issue; warn on watermark skew (issue updated after marker placed; code rewritten
   after issue quiet). Reverse direction (issues lacking location) = rumors *report*,
   never a gate. Migration of tickets into markers = agent labor, not mimir code.
4. **Multi-target scan**: `mimir scan dir1 dir2 ...` → comparative table (the maturity
   view: churn as share-of-recent-commits (not wall time), per-zone ero, todo/ni,
   test presence). Zones are named by the caller, not inferred.
5. **Session attribution** (obol-side): spawn forces worktree+branch encoding session
   id (AFK agents; interactive exempt); harness stamps `Session:` commit trailer
   (survives squash). mimir reads: hunk → live session (branch) or landed session
   (trailer via blame). cwd+timestamps = labeled fallback for foreign sessions.
6. **Deep-link**: "agent said X" → open `file:line@commit`. First join artifact
   between obol sessions and code viewer.
7. **Spawn-from-code**: dispatch agent at a zone with `mimir quests <zone> --json`
   injected as brief. Thin script over obol agents spawn.

Fog (sensed, not ticketable): Slack-for-agents channels with scoped speech (subagents
thread-locked; thread agents form per-zone channels) — obol territory; fleet-view-as-
inbox triage; watch mode / staleness probes for UI aliveness; erosion validation.

## Surfaces (adopt-don't-build, evidence gathered 2026-07-31)

The jump CLI→web is a solved small pattern (plannotator, in `ext/`): stdin JSON →
blocking localhost server → single-file inlined HTML → browser → POST resolves →
stdout JSON. Steal: cookies-not-localStorage (random ports), SSE + `?since=N`,
`/fresh?snapshot=` staleness probe, gate exit codes (0 approved / 1 human-no /
2 misconfigured). Cautionary: never two server runtimes.

- **Units/chat surface = commodity, adopt**: t3code (MIT, 16k★) or omnigent
  (Apache, mobile-ready); parts standard = Vercel AI SDK + AI Elements /
  assistant-ui / shadcn chat primitives. Zed ACP = protocol worth speaking.
- **Terrain surface = ours, later**: file-tree minimap (@pierre/trees, git badges) +
  hunk view with annotation slots (@pierre/diffs — the NPC-symbol slot) + CodeMirror6
  +vim panes (already in parked web/) + plannotator shortcut engine & vim-over-
  semantic-tree (MIT, in ext/) — vim is a grammar, not a terminal artifact; grammar
  over the zone tree (j/k siblings, l descend, h out, f-hints on quest markers).
  Mobile = read-mostly companion posture, not modal grammar.
- No vim-native web IDE exists to fork; don't fork one. $EDITOR stays the teleport
  target for deep editing.
- **Terminal viewer exists — punt web further**: `hunk` (ext/hunk, modem-dev, MIT)
  renders diffs with @pierre/diffs in the terminal, with inline agent annotations.
  v1 surfaces = shell (--at) + $EDITOR keybind + hunk. Web substrate (tiling/buffer
  layer over dockview/react-mosaic — engines exist, keyboard grammar doesn't) stays
  fog until these three can't do something. Strict vim grammar optional, not required.

## Prior art map (why the slot is open)

- Dead read-only joiners: tickgit, todocheck (no repair worker). Dead spatial-
  awareness: Palantír, Crystal (multi-user daemon cost — evaporates when the
  "teammates" are your own agents' worktrees). Dead code maps: Sourcetrail, CodeSee,
  Haystack (pitched navigation; grep wins navigation — sell ambient awareness).
- Swerved survivors: Stepsize (writes into Jira), CodeScene (manager analytics).
- Tracker side: Linear owns branch/PR↔issue for Linear shops + Code Intelligence
  agents; treat issue-refs-in-branch-names as commodity signal we read, never own.
- openai/symphony (ext/symphony, Apache, spec-first): the INVERSE join — tracker
  issue -> spawned agent run -> PR with proof-of-work. Validates the work-management
  layer; competes with obol dispatch, not mimir observation. Its SPEC.md tracker
  integration is the reference for pinned/003's gh (and later Linear) arm.
- Agent side: Beads (issues-in-git for agents — validates the premise, secedes from
  external trackers; cheap hedge: read `.beads/` as a backend someday), DeepWiki
  (code knowledge, no intent join), t3code/omnigent (units surface).
- Games solved it by owning the whole stack (single store, build-checked FKs);
  federated ownership makes clean sync impossible (lenses/RTE) — the mature pattern
  is split custody + FKs + anti-entropy repair, which is exactly this design.

## Out of scope

- Logging/observability/usage reconciliation ("code can only describe what code is").
- Issue-text mining for location (judgment can't be derived; markers cache it).
- Writing to trackers, sync engines, tracker replacement.
- Building chat/fleet UI from scratch.

## Immediate frontier (pre-map)

1. `gh repo create` mimir (private ok) → map + tickets live on mimir's tracker;
   obol-side tickets (spawn policy, trailers) on obol's tracker, linked.
2. Chart the wayfinder map: destination = **CLI primitives we reach for daily on
   obol, compressed from our own repeated usage** — publish & commander view lie
   beyond this map's edge.
