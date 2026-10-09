// Shapes from box/CONTRACT-gateway.md, shared by variants (B) owner-do.ts and (C) fanout-do.ts.
// Times are unix seconds, as the relay (variant A) sends them. Anything that crossed the network
// (a push, the relay's answer) is parsed here into these types; the rest trusts them.

export const END_REASONS = ["stopped", "deadline", "idle", "lease_lost", "boot_failed", "machine_lost"] as const;
export type EndReason = (typeof END_REASONS)[number];

export interface Kernel {
  url: string;
  token: string;
}

export type Status =
  | { state: "booting"; gpu: string | null; started_at: number; deadline: number }
  | { state: "running"; gpu: string | null; started_at: number; deadline: number; kernel: Kernel }
  | { state: "ended"; gpu: string | null; started_at: number; deadline: number; reason: EndReason };

export type GatewayEvent =
  | { t: number; kind: "step"; source: "gateway" | "machine"; text: string }
  | { t: number; kind: "log"; source: "machine"; stream: "stdout" | "stderr"; text: string }
  | { t: number; kind: "status"; status: Status };

export interface Env {
  FANOUT: DurableObjectNamespace<import("./fanout-do").FanoutDO>;
  OWNER: DurableObjectNamespace<import("./owner-do").OwnerDO>;
  RELAY_B: string; // the Python relay that (B)'s DO calls to create / end machines (box SDK)
  RELAY_C: string; // the Python relay (A) that (C) forwards control ops to
  PUSH_SECRET: string; // hex; a session's push key is HMAC(secret, "push:" + id) (box/gateway/push.py)
  DEADLINE_S: string; // (B) the session lifetime the DO's alarm enforces
  SILENT_S: string; // no push from a running machine for this long: it may be gone
  RING_SIZE: string;
  HEARTBEAT_MS: string; // SSE comment pings
}

export const now = (): number => Date.now() / 1000;

export class BadInput extends Error {}

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const bad = (what: string, raw: unknown): never => {
  throw new BadInput(`expected ${what}, got ${JSON.stringify(raw).slice(0, 200)}`);
};

export function parseStatus(raw: unknown): Status {
  if (!isRecord(raw)) return bad("a status object", raw);
  const { state, gpu, started_at, deadline } = raw;
  if ((gpu !== null && typeof gpu !== "string") || typeof started_at !== "number" || typeof deadline !== "number") {
    return bad("status {gpu, started_at, deadline}", raw);
  }
  const base = { gpu, started_at, deadline };
  if (state === "booting") return { state, ...base };
  if (state === "running") {
    const k = raw.kernel;
    if (!isRecord(k) || typeof k.url !== "string" || typeof k.token !== "string") return bad("a running status with kernel {url, token}", raw);
    return { state, ...base, kernel: { url: k.url, token: k.token } };
  }
  const reason = raw.reason;
  if (state === "ended" && END_REASONS.some((r) => r === reason)) return { state, ...base, reason: reason as EndReason };
  return bad("state booting | running | ended(reason)", raw);
}

export function parseEvent(raw: unknown): GatewayEvent {
  if (!isRecord(raw) || typeof raw.t !== "number") return bad("an event {t, kind}", raw);
  const { t, kind, source, text, stream } = raw;
  if (kind === "status") return { t, kind, status: parseStatus(raw.status) };
  if (kind === "step" && (source === "gateway" || source === "machine") && typeof text === "string") return { t, kind, source, text };
  if (kind === "log" && source === "machine" && (stream === "stdout" || stream === "stderr") && typeof text === "string") {
    return { t, kind, source, stream, text };
  }
  return bad("a step, log or status event", raw);
}

export interface ModalToken {
  id: string;
  secret: string;
}

// POST /sessions's body, only as far as the Worker needs it (the relay parses all of it).
export function parseCreateToken(raw: unknown): ModalToken {
  const token = isRecord(raw) ? raw.token : undefined;
  if (!isRecord(token) || typeof token.id !== "string" || typeof token.secret !== "string" || !token.id || !token.secret) {
    return bad("{token: {id, secret}}", raw);
  }
  return { id: token.id, secret: token.secret };
}

// The relay's 202: {session_id, status}.
export function parseCreated(raw: unknown): { session_id: string; status: Status } {
  if (!isRecord(raw) || typeof raw.session_id !== "string" || !/^s-[0-9a-f]{12}$/.test(raw.session_id)) {
    return bad("{session_id: s-<12 hex>, status}", raw);
  }
  return { session_id: raw.session_id, status: parseStatus(raw.status) };
}
