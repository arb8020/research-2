// One Durable Object per session id. In this spike it is the (C)-shaped core that (B) grows from:
//   - durable bounded event log + SSE fan-out with Last-Event-ID replay
//   - producer ingest from the machine: HTTP POST (NDJSON) or a hibernatable websocket
//   - a deadline alarm (the "DO owns the deadline" option)
//   - a token-injecting reverse proxy to the machine's kernel (Jupyter Server)
// It does not create/kill machines (no Modal from Workers); that stays in a Python control service.

import { DurableObject } from "cloudflare:workers";
import { EventLog } from "./event-log";
import { proxy, type Upstream } from "./proxy";
import { frame, SseHub } from "./sse";
import type { EndReason, Env, GatewayEvent, Status } from "./types";

const json = (o: unknown, status = 200) =>
  new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json" } });

export class SessionDO extends DurableObject<Env> {
  private log: EventLog;
  private hub: SseHub;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)");
    this.log = new EventLog(ctx.storage.sql, Number(env.RING_SIZE));
    this.hub = new SseHub(Number(env.HEARTBEAT_MS));
  }

  // The Worker forwards /sessions/{id}{rest} with headers x-session-id and x-gateway-origin.
  async fetch(req: Request): Promise<Response> {
    const id = req.headers.get("x-session-id")!;
    const rest = new URL(req.url).pathname.replace(/^\/sessions\/[^/]+/, "");
    const m = req.method;

    if (rest.startsWith("/kernel")) return this.proxyKernel(req, rest.slice("/kernel".length) || "/");
    if (rest === "" && m === "GET") return json({ session_id: id, status: this.status() });
    if (rest === "/events" && m === "GET") return this.subscribe(req);
    if (rest === "/end" && m === "POST") return json({ status: this.end("stopped") });

    // producer (machine / control service) routes
    if (!this.machineAuthorized(req)) return json({ error: "bad machine key" }, 401);
    if (rest === "/events" && m === "POST") return json({ last_seq: this.ingest(await req.text()) });
    if (rest === "/machine" && m === "GET") return this.acceptMachine(req);
    if (rest === "/deadline" && m === "POST") return json({ status: await this.setDeadline(await req.json()) });
    if (rest === "/upstream" && m === "POST") {
      return json({ status: this.setUpstream(await req.json(), id, req.headers.get("x-gateway-origin")!) });
    }
    return json({ error: `no route ${m} ${rest}` }, 404);
  }

  // ---- events ----

  private subscribe(req: Request): Response {
    const url = new URL(req.url);
    const last = Number(req.headers.get("last-event-id") ?? url.searchParams.get("last_event_id") ?? 0);
    const { events, dropped } = this.log.since(last);
    let backlog = "";
    if (dropped > 0 && last > 0) {
      // Unnumbered so it doesn't move the client's Last-Event-ID.
      const gap: GatewayEvent = { t: Date.now(), kind: "step", source: "gateway", text: `replay gap: ${dropped} events dropped` };
      backlog += `data: ${JSON.stringify(gap)}\n\n`;
    }
    backlog += events.map(frame).join("");
    return this.hub.open(backlog);
  }

  private publish(event: GatewayEvent): number {
    const stored = this.log.append(event);
    this.hub.broadcast(frame(stored));
    return stored.seq;
  }

  // Body: one JSON event per line (NDJSON). Missing `t` is stamped here; `source` defaults to machine.
  private ingest(body: string): number {
    let seq = this.log.lastSeq();
    for (const line of body.split("\n")) {
      if (!line.trim()) continue;
      const e = JSON.parse(line);
      seq = this.publish({ t: Date.now(), source: "machine", ...e });
    }
    return seq;
  }

  // ---- machine websocket (hibernation API: the DO may sleep while the machine is quiet) ----

  private acceptMachine(req: Request): Response {
    if (req.headers.get("upgrade")?.toLowerCase() !== "websocket") return json({ error: "expected websocket" }, 426);
    const pair = new WebSocketPair();
    this.ctx.acceptWebSocket(pair[1], ["machine"]);
    return new Response(null, { status: 101, webSocket: pair[0] });
  }

  async webSocketMessage(ws: WebSocket, msg: string | ArrayBuffer): Promise<void> {
    const seq = this.ingest(typeof msg === "string" ? msg : new TextDecoder().decode(msg));
    ws.send(JSON.stringify({ ack: seq }));
  }

  async webSocketClose(ws: WebSocket, code: number): Promise<void> {
    this.publish({ t: Date.now(), kind: "step", source: "gateway", text: `machine socket closed (${code})` });
  }

  // ---- status / deadline ----

  private status(): Status {
    const raw = this.meta("status");
    if (raw) return JSON.parse(raw);
    const s: Status = { state: "booting", gpu: null, started_at: Date.now(), deadline: null };
    this.setMeta("status", JSON.stringify(s));
    return s;
  }

  private setStatus(s: Status): Status {
    this.setMeta("status", JSON.stringify(s));
    this.publish({ t: Date.now(), kind: "status", status: s });
    return s;
  }

  private async setDeadline(body: { deadline?: number; in_ms?: number }): Promise<Status> {
    const deadline = body.deadline ?? Date.now() + (body.in_ms ?? 0);
    await this.ctx.storage.setAlarm(deadline);
    return this.setStatus({ ...this.status(), deadline });
  }

  async alarm(): Promise<void> {
    const s = this.status();
    if (s.state === "ended") return;
    if (s.deadline && Date.now() < s.deadline) return void (await this.ctx.storage.setAlarm(s.deadline));
    this.publish({ t: Date.now(), kind: "step", source: "gateway", text: `deadline reached (alarm fired, late by ${Date.now() - (s.deadline ?? 0)} ms)` });
    this.end("deadline");
    // (B) would also call the Python control service here to terminate the machine.
  }

  private end(reason: EndReason): Status {
    const s = this.status();
    if (s.state === "ended") return s;
    return this.setStatus({ ...s, state: "ended", reason, kernel: undefined });
  }

  // ---- kernel proxy ----

  private setUpstream(up: Upstream & { gpu?: string }, id: string, origin: string): Status {
    this.setMeta("upstream", JSON.stringify({ url: up.url, token: up.token }));
    const kernel = { url: `${origin}/sessions/${id}/kernel`, token: "via-gateway" };
    return this.setStatus({ ...this.status(), state: "running", gpu: up.gpu ?? null, kernel });
  }

  private async proxyKernel(req: Request, rest: string): Promise<Response> {
    const raw = this.meta("upstream");
    if (!raw) return json({ error: "no upstream yet" }, 503);
    const url = new URL(req.url);
    url.searchParams.delete("token"); // the browser's placeholder token must not reach Jupyter
    return proxy(new Request(url, req), JSON.parse(raw), rest);
  }

  // ---- helpers ----

  private machineAuthorized(req: Request): boolean {
    return !this.env.MACHINE_KEY || req.headers.get("x-machine-key") === this.env.MACHINE_KEY;
  }

  private meta(k: string): string | null {
    return this.ctx.storage.sql.exec<{ v: string }>("SELECT v FROM meta WHERE k = ?", k).toArray()[0]?.v ?? null;
  }

  private setMeta(k: string, v: string): void {
    this.ctx.storage.sql.exec("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", k, v);
  }
}
