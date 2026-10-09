// HTTP client for the Connect gateway (box/CONTRACT-gateway.md, "Control"). Everything the gateway sends is
// parsed here into the types below; the rest of connect/ trusts them.
import type { KernelAddress } from "./kernel";

export interface Token {
  id: string;
  secret: string;
}

// "lease": the session length ran out. "deadline" is the same thing from relays older than the lease (still accepted).
export const ENDED_REASONS = ["stopped", "lease", "deadline", "idle", "lease_lost", "boot_failed", "machine_lost"] as const;
export type EndedReason = (typeof ENDED_REASONS)[number];

// Session length (POST /sessions lease_s): the gateway accepts 60..43200 s and caps extends at start + 12 h.
export const LEASE_MIN_S = 60;
export const LEASE_MAX_S = 12 * 3600;

// leaseUntil: when the session ends unless extended (unix s). ceiling: the latest an extend can push it to
// (start + 12 h); undefined from a relay older than the lease, which can't extend.
interface Times {
  gpu: string | null;
  startedAt: number;
  leaseUntil: number;
  ceiling: number | undefined;
}
export type Status =
  | ({ state: "booting" } & Times)
  | ({ state: "running"; kernel: KernelAddress } & Times)
  | ({ state: "ended"; reason: EndedReason } & Times);

export type GatewayEvent =
  | { t: number; kind: "step"; source: "gateway" | "machine"; text: string }
  | { t: number; kind: "log"; source: "machine"; stream: "stdout" | "stderr"; text: string }
  | { t: number; kind: "status"; status: Status };

export class GatewayError extends Error {}

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const fail = (what: string, raw: unknown): never => {
  throw new GatewayError(`gateway: expected ${what}, got ${JSON.stringify(raw).slice(0, 300)}`);
};
const isReason = (x: unknown): x is EndedReason => ENDED_REASONS.some((r) => r === x);

export function parseStatus(raw: unknown): Status {
  if (!isRecord(raw)) return fail("a status object", raw);
  const { state, gpu, started_at: startedAt, deadline, ceiling } = raw;
  // An older relay has no lease_until; its deadline means the same thing (when the session ends).
  const leaseUntil = raw["lease_until"] ?? deadline;
  if ((gpu !== null && typeof gpu !== "string") || typeof startedAt !== "number" || typeof leaseUntil !== "number") {
    return fail("status {gpu: string | null, started_at: number, lease_until (or deadline): number}", raw);
  }
  if (ceiling !== undefined && (typeof ceiling !== "number" || ceiling < startedAt)) return fail("status ceiling: a unix time after started_at", raw);
  const base = { gpu, startedAt, leaseUntil, ceiling };
  if (state === "booting") return { state, ...base };
  if (state === "running") {
    const k = raw["kernel"];
    if (!isRecord(k) || typeof k["url"] !== "string" || typeof k["token"] !== "string") return fail("a running status with kernel {url, token}", raw);
    return { state, ...base, kernel: { url: k["url"].replace(/\/$/, ""), token: k["token"] } };
  }
  if (state === "ended") return isReason(raw["reason"]) ? { state, ...base, reason: raw["reason"] } : fail(`an ended status with reason in ${ENDED_REASONS.join("|")}`, raw);
  return fail("state booting | running | ended", raw);
}

export function parseEvent(raw: unknown): GatewayEvent {
  if (!isRecord(raw) || typeof raw["t"] !== "number") return fail("an event {t, kind, ...}", raw);
  const { t, kind, source, text } = raw;
  if (kind === "status") return { t, kind, status: parseStatus(raw["status"]) };
  if (kind === "step" && (source === "gateway" || source === "machine") && typeof text === "string") return { t, kind, source, text };
  const stream = raw["stream"];
  if (kind === "log" && source === "machine" && (stream === "stdout" || stream === "stderr") && typeof text === "string") return { t, kind, source, stream, text };
  return fail("a step, log or status event", raw);
}

const auth = (token: Token): string => `${token.id}:${token.secret}`;

async function call(url: string, init: RequestInit): Promise<unknown> {
  const res = await fetch(url, init); // a TypeError here means unreachable; callers say so
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const why = isRecord(body) && typeof body["error"] === "string" ? body["error"] : `HTTP ${String(res.status)}`;
    throw new GatewayError(`gateway ${init.method ?? "GET"} ${new URL(url).pathname}: ${why}`, { cause: res.status });
  }
  return body;
}

export async function createSession(gateway: string, token: Token, gpu: string | null, leaseS: number): Promise<{ id: string; status: Status }> {
  if (!Number.isInteger(leaseS)) throw new Error(`createSession: lease_s must be whole seconds, got ${String(leaseS)}`);
  if (leaseS < LEASE_MIN_S || leaseS > LEASE_MAX_S) throw new Error(`createSession: lease_s ${String(leaseS)} outside ${String(LEASE_MIN_S)}..${String(LEASE_MAX_S)}`);
  const body = await call(`${gateway}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: "modal", token, gpu, lease_s: leaseS, labels: { "box.caller": "blogs" } }),
  });
  if (!isRecord(body) || typeof body["session_id"] !== "string") return fail("{session_id, status}", body);
  return { id: body["session_id"], status: parseStatus(body["status"]) };
}

// The session's status, or "gone" if the gateway no longer knows it (404).
export async function getSession(gateway: string, id: string, token: Token): Promise<Status | "gone"> {
  try {
    const body = await call(`${gateway}/sessions/${encodeURIComponent(id)}`, { headers: { "X-Box-Token": auth(token) } });
    return isRecord(body) ? parseStatus(body["status"]) : fail("{session_id, status}", body);
  } catch (e) {
    if (e instanceof GatewayError && e.cause === 404) return "gone";
    throw e;
  }
}

export async function endSession(gateway: string, id: string, token: Token): Promise<void> {
  await call(`${gateway}/sessions/${encodeURIComponent(id)}/end`, { method: "POST", headers: { "X-Box-Token": auth(token) } });
}

// Push the lease to `until` (unix s). The gateway clamps it to the status's ceiling; the returned status says where it landed.
export async function extendSession(gateway: string, id: string, token: Token, until: number): Promise<Status> {
  const body = await call(`${gateway}/sessions/${encodeURIComponent(id)}/extend`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Box-Token": auth(token) },
    body: JSON.stringify({ until }),
  });
  return isRecord(body) ? parseStatus(body["status"]) : fail("{status}", body);
}

// SSE subscription; EventSource resumes with Last-Event-ID by itself. Returns close().
export function subscribe(gateway: string, id: string, token: Token, onEvent: (e: GatewayEvent) => void, onBroken: () => void): () => void {
  const source = new EventSource(`${gateway}/sessions/${encodeURIComponent(id)}/events?token=${encodeURIComponent(auth(token))}`);
  source.onmessage = (m) => { onEvent(parseEvent(JSON.parse(String(m.data)))); };
  source.onerror = () => { if (source.readyState === EventSource.CLOSED) onBroken(); }; // CONNECTING = it retries itself
  return () => { source.close(); };
}
