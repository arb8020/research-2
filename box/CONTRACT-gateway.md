# Browser <-> gateway contract (draft v0, 2026-10-09 night)

One HTTP API that all three session-owner variants implement, so the page doesn't care which one runs
and the comparison is apples to apples:
- (A) `relay` : Python, stateless, box SDK; the machine (supervisor) owns the session.
- (C) `fanout`: Worker + Durable Object in front of (A); DO only fans out logs / proxies; never owns the lease,
  never stores the token. It may call the Python relay for control ops.
- (B) `do-owns`: Worker + DO holds canonical session state + log ring buffer + token (for the session lifetime);
  calls a Python control service (box SDK) to create/kill machines.

Base URL is configured on the page (`data-gateway="http://localhost:8790"`). CORS: allow the page origin.

## Control
```
GET  /limits                       no token -> {lease:{min_s, max_s, default_s}, ceiling_s, gpus:[string|null]}
                                   what this gateway accepts (the relay's flags; default 60, 43200, 5400, 43200, [null, "T4"])
POST /sessions                     body {provider:"modal", token:{id, secret}, gpu:"T4"|null, labels?:{}, lease_s?:int}
                                   lease_s: min_s..max_s (default default_s); else 400. The session ends when its lease
                                   does, at most ceiling_s after it was created (its ceiling).
                                   -> 202 {session_id, status}          returns immediately; boot continues
GET  /sessions/{id}                header X-Box-Token: <id>:<secret> (A/C; B ignores)
                                   -> {session_id, status}
POST /sessions/{id}/end            -> {session_id, status}
POST /sessions/{id}/extend         header X-Box-Token; body {until} (unix seconds)
                                   -> {session_id, status} lease_until becomes until, clamped to ceiling; never shorter (an
                                   earlier until changes nothing). 409 while the session is booting (machine not up).
GET  /sessions/{id}/events         SSE (text/event-stream). Each event is one JSON object:
                                     {t, kind:"step", source:"gateway"|"machine", text}      human-readable progress
                                     {t, kind:"log",  source:"machine", stream:"stdout"|"stderr", text}
                                     {t, kind:"status", status}
                                   Reconnect with Last-Event-ID resumes (B/C from ring buffer; A best effort).
                                   (EventSource can't set headers: token goes as ?token= for A/C over localhost dev.)
```
`status` = `{state:"booting"|"running"|"ended", gpu, started_at, lease_until, ceiling, reason?, kernel?:{url, token}}`
`lease_until`, `ceiling`: unix seconds. `started_at`: unix seconds the machine's supervisor started (booting: now);
null on an ended session whose machine never started.
`reason` (ended) = `"stopped"|"lease"|"idle"|"boot_failed"|"machine_lost"`. Idle (no connection to the kernel
for the relay's idle timeout) stays on: a closed tab ends the session even with lease left.
`kernel` appears once running: a Jupyter Server base URL + token reachable from the browser (A: Modal tunnel
direct; B/C: may be a DO-proxied URL).

## Cells
The page talks Jupyter Server REST + kernel websocket (`/api/kernels`, `/api/kernels/{k}/channels`) at
`status.kernel.url` with `token`. One kernel per session. Cells are `execute_request`s; output from iopub
`stream` / `error` / `execute_result`.
- scratch cell (`nvidia-smi`): code `!nvidia-smi` or `subprocess` — shell via IPython `!`.
- nn-fit remote: page sends a self-contained Python training program (torch) + a JSON config; the program prints
  one JSON line per progress tick to stdout: `{"step":..,"loss":..,"pred":[...]}`; the widget plots them. Stop =
  Jupyter interrupt.

## Browser storage
`localStorage["connect.token.modal"] = {id, secret}` (masked in UI; Sign out deletes);
`localStorage["connect.session"] = {gateway, session_id, provider, gpu}` -> carry-over across pages: on load,
GET /sessions/{id}; if running, reattach; if ended, clear.
