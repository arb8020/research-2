import type { KernelAddress } from "./kernel";
import { isJsonObject } from "../json";

export interface Token {
  id: string;
  secret: string;
}

export const ENDED_REASONS = ["stopped", "lease", "idle", "boot_failed", "machine_lost"] as const;
export type EndedReason = (typeof ENDED_REASONS)[number];

export const LEASE_MIN_S = 60;
export const LEASE_MAX_S = 12 * 3600;

interface Times {
  gpu: string | null;
  leaseUntil: number;
  ceiling: number;
}
export type Status =
  | ({ state: "booting"; startedAt: number } & Times)
  | ({ state: "running"; startedAt: number; kernel: KernelAddress } & Times)
  | ({ state: "ended"; startedAt: number | null; reason: EndedReason } & Times);

export type GatewayEvent =
  | { t: number; kind: "step"; source: "gateway" | "machine"; text: string }
  | { t: number; kind: "log"; source: "machine"; stream: "stdout" | "stderr"; text: string }
  | { t: number; kind: "status"; status: Status };

export class GatewayError extends Error {}

export const redacted = (raw: unknown): string =>
  JSON.stringify(raw, (k, v: unknown) => (k === "token" || k === "secret" ? "[redacted]" : v));
const fail = (what: string, raw: unknown): never => {
  throw new GatewayError(`gateway: expected ${what}, got ${redacted(raw).slice(0, 300)}`);
};
const isReason = (x: unknown): x is EndedReason => ENDED_REASONS.some((r) => r === x);

export function parseStatus(raw: unknown): Status {
  if (!isJsonObject(raw)) return fail("a status object", raw);
  const { state, gpu, started_at: startedAt, lease_until: leaseUntil, ceiling } = raw;
  if (gpu !== null && typeof gpu !== "string") return fail("status {gpu: string | null}", raw);
  if (startedAt !== null && typeof startedAt !== "number") return fail("status {started_at: number | null}", raw);
  if (typeof leaseUntil !== "number" || typeof ceiling !== "number") return fail("status {lease_until: number, ceiling: number} (a gateway with session leases)", raw);
  if (startedAt !== null && ceiling < startedAt) return fail("status ceiling: a unix time after started_at", raw);
  const base = { gpu, leaseUntil, ceiling };
  if (state === "ended") return isReason(raw["reason"]) ? { state, startedAt, ...base, reason: raw["reason"] } : fail(`an ended status with reason in ${ENDED_REASONS.join("|")}`, raw);
  if (startedAt === null) return fail("status started_at: null only on an ended session", raw);
  if (state === "booting") return { state, startedAt, ...base };
  if (state === "running") {
    const k = raw["kernel"];
    if (!isJsonObject(k) || typeof k["url"] !== "string" || typeof k["token"] !== "string") return fail("a running status with kernel {url, token}", raw);
    return { state, startedAt, ...base, kernel: { url: k["url"].replace(/\/$/, ""), token: k["token"] } };
  }
  return fail("state booting | running | ended", raw);
}

export function parseEvent(raw: unknown): GatewayEvent {
  if (!isJsonObject(raw) || typeof raw["t"] !== "number") return fail("an event {t, kind, ...}", raw);
  const { t, kind, source, text } = raw;
  if (kind === "status") return { t, kind, status: parseStatus(raw["status"]) };
  if (kind === "step" && (source === "gateway" || source === "machine") && typeof text === "string") return { t, kind, source, text };
  const stream = raw["stream"];
  if (kind === "log" && source === "machine" && (stream === "stdout" || stream === "stderr") && typeof text === "string") return { t, kind, source, stream, text };
  return fail("a step, log or status event", raw);
}

const auth = (token: Token): string => `${token.id}:${token.secret}`;

async function call(url: string, init: RequestInit): Promise<unknown> {
  const res = await fetch(url, init);
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const why = isJsonObject(body) && typeof body["error"] === "string" ? body["error"] : `HTTP ${String(res.status)}`;
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
  if (!isJsonObject(body) || typeof body["session_id"] !== "string") return fail("{session_id, status}", body);
  return { id: body["session_id"], status: parseStatus(body["status"]) };
}

export async function getSession(gateway: string, id: string, token: Token): Promise<Status | "gone"> {
  try {
    const body = await call(`${gateway}/sessions/${encodeURIComponent(id)}`, { headers: { "X-Box-Token": auth(token) } });
    return isJsonObject(body) ? parseStatus(body["status"]) : fail("{session_id, status}", body);
  } catch (cause) {
    if (cause instanceof GatewayError && cause.cause === 404) return "gone";
    throw cause;
  }
}

export async function endSession(gateway: string, id: string, token: Token): Promise<void> {
  await call(`${gateway}/sessions/${encodeURIComponent(id)}/end`, { method: "POST", headers: { "X-Box-Token": auth(token) } });
}

export async function extendSession(gateway: string, id: string, token: Token, until: number): Promise<Status> {
  const body = await call(`${gateway}/sessions/${encodeURIComponent(id)}/extend`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Box-Token": auth(token) },
    body: JSON.stringify({ until }),
  });
  return isJsonObject(body) ? parseStatus(body["status"]) : fail("{status}", body);
}

export function subscribe(
  gateway: string, id: string, token: Token, onEvent: (e: GatewayEvent) => void, onBroken: () => void, onBadEvent: (e: GatewayError) => void,
): () => void {
  const source = new EventSource(`${gateway}/sessions/${encodeURIComponent(id)}/events?token=${encodeURIComponent(auth(token))}`);
  source.onmessage = (m) => {
    let event: GatewayEvent;
    try {
      event = parseEvent(JSON.parse(String(m.data)));
    } catch (cause) {
      source.close();
      onBadEvent(cause instanceof GatewayError ? cause : new GatewayError(`gateway: an event that is not JSON: ${String(m.data).slice(0, 300)}`, { cause }));
      return;
    }
    onEvent(event);
  };
  source.onerror = () => { if (source.readyState === EventSource.CLOSED) onBroken(); };
  return () => { source.close(); };
}
