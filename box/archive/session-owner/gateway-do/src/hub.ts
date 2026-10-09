// What both Durable Objects are: one per session, a bounded durable event log (SQLite) fanned out to
// readers over SSE with Last-Event-ID replay, fed by pushes (the relay's boot events, then the
// machine's forwarder). Each variant says what a pushed status means (onStatus) and what a silent
// machine means (onSilent); (B) adds a deadline (deadlineAt) and owns the status, (C) does neither.
//
// meta (key -> JSON): digest (sha256 of the reader's "id:secret"; who may read), heard (unix s of the
// last push), watching (a running machine is expected to push), announced (the `heard` a silence was
// already reported for). Subclasses add their own keys.

import { DurableObject } from "cloudflare:workers";
import { EventLog } from "./event-log";
import { frame, SseHub } from "./sse";
import { BadInput, now, parseEvent, type Env, type GatewayEvent } from "./types";

export const MAX_PUSH_BYTES = 1 << 20;
export const MAX_PUSH_EVENTS = 1000;

export const json = (o: unknown, status = 200): Response =>
  new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json" } });

export async function sha256hex(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function parsePush(body: string): GatewayEvent[] {
  if (body.length > MAX_PUSH_BYTES) throw new BadInput(`push over ${MAX_PUSH_BYTES} bytes`);
  const lines = body.split("\n").filter((l) => l.trim());
  if (lines.length > MAX_PUSH_EVENTS) throw new BadInput(`push of ${lines.length} events; at most ${MAX_PUSH_EVENTS}`);
  return lines.map((l) => parseEvent(JSON.parse(l)));
}

export abstract class Hub extends DurableObject<Env> {
  protected log: EventLog;
  private hub: SseHub;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)");
    this.log = new EventLog(ctx.storage.sql, Number(env.RING_SIZE));
    this.hub = new SseHub(Number(env.HEARTBEAT_MS));
  }

  // ---- variant hooks ----

  protected abstract onStatus(event: Extract<GatewayEvent, { kind: "status" }>): Promise<void>;
  protected abstract onSilent(silentFor: number): Promise<void>;
  protected deadlineAt(): number | null {
    return null; // (C): the machine owns the deadline
  }
  protected async onDeadline(): Promise<void> {
    throw new Error("onDeadline without a deadline");
  }
  protected kernel(_req: Request, _rest: string): Promise<Response> | Response {
    return json({ error: "this gateway does not proxy the kernel: use status.kernel.url" }, 404);
  }

  // ---- producer: the Worker checked the push key ----

  // An empty body is a heartbeat. A bad push changes nothing: {error} (the Worker answers 400).
  async push(body: string): Promise<{ last_seq: number } | { error: string }> {
    let events: GatewayEvent[];
    try {
      events = parsePush(body);
    } catch (e) {
      if (e instanceof BadInput || e instanceof SyntaxError) return { error: e.message };
      throw e;
    }
    this.setMeta("heard", now());
    for (const e of events) {
      if (e.kind === "status") await this.onStatus(e);
      else this.publish(e);
    }
    await this.arm();
    return { last_seq: this.log.lastSeq() };
  }

  // ---- readers ----

  // /events (SSE) and, for (B), /kernel/*. The Worker forwards /sessions/{id}{rest} here.
  async fetch(req: Request): Promise<Response> {
    const url = new URL(req.url);
    const rest = url.pathname.replace(/^(\/[bc])?\/sessions\/[^/]+/, "");
    if (rest.startsWith("/kernel")) return this.kernel(req, rest.slice("/kernel".length) || "/");
    if (rest !== "/events" || req.method !== "GET") return json({ error: `no route ${req.method} ${rest}` }, 404);
    const denied = await this.denied(url.searchParams.get("token") ?? "");
    if (denied) return denied;
    const last = Number(req.headers.get("last-event-id") ?? 0);
    const { events, dropped } = this.log.since(Number.isInteger(last) && last > 0 ? last : 0);
    const gap: GatewayEvent = { t: now(), kind: "step", source: "gateway", text: `replay gap: ${dropped} events dropped` };
    const backlog = (dropped > 0 && last > 0 ? `data: ${JSON.stringify(gap)}\n\n` : "") + events.map(frame).join("");
    return this.hub.open(backlog);
  }

  // The reader's X-Box-Token / ?token= ("id:secret") against the digest kept at create. 404 for a
  // session this gateway never created (nothing says whether it exists), 403 for a wrong token.
  protected async denied(auth: string): Promise<Response | null> {
    const digest = this.meta<string>("digest");
    if (digest === null) return json({ error: "no such session on this gateway" }, 404);
    return (await sha256hex(auth)) === digest ? null : json({ error: "token does not match the session's" }, 403);
  }

  // ---- shared state changes ----

  protected publish(event: GatewayEvent): void {
    this.hub.broadcast(frame(this.log.append(event)));
  }

  protected step(text: string): void {
    this.publish({ t: now(), kind: "step", source: "gateway", text });
  }

  protected watch(on: boolean): void {
    this.setMeta("watching", on);
  }

  // One alarm serves both clocks: the deadline ((B) only) and the silence watch.
  protected async arm(): Promise<void> {
    const heard = this.meta<number>("heard");
    const silentAt = this.meta<boolean>("watching") && heard !== null && this.meta<number>("announced") !== heard ? heard + Number(this.env.SILENT_S) : null;
    const next = [silentAt, this.deadlineAt()].filter((t): t is number => t !== null);
    if (next.length) await this.ctx.storage.setAlarm(Math.min(...next) * 1000);
    else await this.ctx.storage.deleteAlarm();
  }

  async alarm(): Promise<void> {
    const deadline = this.deadlineAt();
    const heard = this.meta<number>("heard");
    if (deadline !== null && now() >= deadline) {
      await this.onDeadline();
    } else if (this.meta<boolean>("watching") && heard !== null && now() - heard >= Number(this.env.SILENT_S)) {
      this.setMeta("announced", heard);
      await this.onSilent(now() - heard);
    }
    await this.arm();
  }

  // ---- meta ----

  protected meta<T>(k: string): T | null {
    const v = this.ctx.storage.sql.exec<{ v: string }>("SELECT v FROM meta WHERE k = ?", k).toArray()[0]?.v;
    return v === undefined ? null : (JSON.parse(v) as T);
  }

  protected setMeta(k: string, v: unknown): void {
    this.ctx.storage.sql.exec("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", k, JSON.stringify(v));
  }

  protected dropMeta(...keys: string[]): void {
    for (const k of keys) this.ctx.storage.sql.exec("DELETE FROM meta WHERE k = ?", k);
  }
}
