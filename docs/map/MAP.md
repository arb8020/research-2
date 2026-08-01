# Wayfinder map: mimir CLI primitives with gravity
<!-- wayfinder:map · tracker: local-markdown (docs/map/) · charted 2026-08-01 -->

## Destination

Mimir + obol CLI primitives that we reach for daily on obol, compressed from our own
repeated usage — each level trivially decomposable into the one below. GitHub publish
and the commander/web surfaces lie beyond this map's edge.

## Notes

- **Execution override**: this map carries execution — tickets are build work as well
  as decisions. Definition of done for build tickets: matklad-style boundary tests +
  manually proven on obol.
- Context anchor: [docs/VISION.md](../VISION.md) (thesis, principles, custody rules,
  parts survey, prior art). Consult before any ticket.
- Skills/docs per session: ~/research/docs/code_style/style_reference.md (shapes),
  how_to_test_matklad.md (tests), casey_granularity.md (feature admission: manual
  first, compress on second reach).
- Obol-side tickets live on obol's GitHub tracker, linked below; a session claims a
  local ticket by setting `assignee:` in its front-matter.
- Tickets: docs/map/tickets/NNN-slug.md. Status lives in front-matter
  (open/claimed/closed). Frontier = open + unblocked + unassigned.

## Ratifications (2026-08-01 audit)

All previously-inferred decisions walked one-by-one and ruled on: (1) pinned v1
gh-only, v0 pure git; (2) custody model (a) — comments are the link, mimir never
writes; b-prime pinned ranges deferred to fog; (3) fleet surface punted,
adopt-vs-build deliberately open; (4) map composition confirmed — --at first,
deep-link stays fog, 008 parked; (5) local-markdown tracker confirmed;
(6) read-only-forever confirmed (via 2).

## Decisions so far

<!-- one line per closed ticket: gist + link -->

- [research: hunk annotation interface (007)](tickets/007-research-hunk-annotations.md) — no upstream PR needed: target `--agent-context` sidecar JSON v1; watch mode live-reloads the sidecar; ranges preserved (session daemon is single-line only)

## Not yet specified

- Slack-for-agents channels with scoped speech (obol; conversations layer)
- Fleet-view-as-inbox; deep-link "agent said X" → file:line@commit (needs obol
  session data shape)
- Spawn-from-code / zone-brief dispatch glue
- Web substrate (tiling/buffer layer) — waits until shell + $EDITOR + hunk can't do
  something we need
- Watch mode / staleness probes for surface aliveness
- Erosion validation against real human/agent corpora; README + publish
- Reading .beads/ as a tracker backend (hedge)
- Commit-pinned range sidecar (b-prime): optional precision layer over markers,
  deferred until coarse markers prove insufficient (see VISION fog)

## Out of scope

- Logging/observability/usage reconciliation — code can only describe what code is
- Issue-text mining for location — judgment can't be derived; markers cache it
- Writing to trackers, sync engines, tracker replacement
- Fleet/chat surface for now (punted; adopt-vs-build deliberately open — VISION)

## Tickets

Frontier: [001](tickets/001-at-query.md) · [003](tickets/003-pinned-markers.md) ·
[005](tickets/005-multi-target-scan.md) · [008](tickets/008-grill-erosion-demotion.md) · [spawn forces worktree+branch (obol#646)](https://github.com/silares-ai/obol/issues/646) · [Session commit trailer (obol#647)](https://github.com/silares-ai/obol/issues/647)

Blocked: [002](tickets/002-active-quests.md) (by 001) ·
[004](tickets/004-check-ci-gate.md) (by 003) ·
[006](tickets/006-emit-hunk-annotations.md) (by 001)
