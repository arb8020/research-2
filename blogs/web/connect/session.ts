import { createSession, endSession, extendSession, getLimits, getSession, subscribe } from "./gateway";
import type { EndedReason, GatewayEvent, Limits, Status, Token } from "./gateway";
import { attach, detach, onKernelState } from "./kernel";
import { isJsonObject } from "../json";

export type Phase =
  | { kind: "disconnected"; failure: string | undefined }
  | { kind: "connecting"; gpu: string | null; step: string }
  | { kind: "connected"; id: string; gpu: string | null; startedAt: number; leaseUntil: number; ceiling: number };

export interface LogLine {
  t: number;
  source: "gateway" | "machine" | "page";
  kind: "step" | "log" | "error";
  text: string;
}

interface Stored {
  gateway: string;
  session_id: string;
  provider: "modal";
  gpu: string | null;
}

const TOKEN_KEY = "connect.token.modal";
const SESSION_KEY = "connect.session";
const MAX_LOG = 2000;
const REATTACH_GAP_MS = 10_000;

const REASONS: Record<EndedReason, string | undefined> = {
  stopped: "the session was stopped outside this page (another tab, or released)",
  lease: "the session length ran out (Connect again to keep going)",
  idle: "the session was idle too long and was stopped",
  boot_failed: "the machine failed to start (see Details)",
  machine_lost: "the machine went away",
};

let phase: Phase = { kind: "disconnected", failure: undefined };
let dropped = 0;
const log: LogLine[] = [];
const phaseListeners = new Set<(p: Phase) => void>();
const logListeners = new Set<(line: LogLine) => void>();
let live: { stored: Stored; token: Token; close: () => void } | undefined;
let lastReattach = 0;
let attaching = false;

function gatewayUrl(): string {
  const fromQuery = new URLSearchParams(location.search).get("gateway");
  const url = fromQuery !== null && fromQuery !== "" ? fromQuery : document.querySelector("connect-pill")?.getAttribute("data-gateway") ?? "";
  if (url === "") throw new Error("connect: no gateway URL (<connect-pill data-gateway> or ?gateway=)");
  return url.replace(/\/$/, "");
}
let gatewayCache: string | undefined;
const gateway = (): string => (gatewayCache ??= gatewayUrl());

export const currentPhase = (): Phase => phase;
export const limits = (): Promise<Limits> => getLimits(gateway());
export const logLines = (): { lines: readonly LogLine[]; dropped: number } => ({ lines: log, dropped });
export function onPhase(listener: (p: Phase) => void): () => void {
  phaseListeners.add(listener);
  return () => { phaseListeners.delete(listener); };
}
export function onLog(listener: (line: LogLine) => void): () => void {
  logListeners.add(listener);
  return () => { logListeners.delete(listener); };
}

function setPhase(next: Phase): void {
  phase = next;
  for (const listener of phaseListeners) listener(next);
}

function append(line: LogLine): void {
  log.push(line);
  if (log.length > MAX_LOG) { log.shift(); dropped += 1; }
  for (const listener of logListeners) listener(line);
}
const note = (text: string, kind: "step" | "error" = "step"): void => { append({ t: Date.now() / 1000, source: "page", kind, text }); };

const readJson = (key: string): unknown => {
  try { return JSON.parse(localStorage.getItem(key) ?? "null"); } catch { return null; }
};
const writeJson = (key: string, value: unknown): void => {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch { return; }
};

export function savedToken(): Token | undefined {
  const raw = readJson(TOKEN_KEY);
  if (typeof raw !== "object" || raw === null || !("id" in raw) || !("secret" in raw)) return undefined;
  const { id, secret } = raw;
  return typeof id === "string" && typeof secret === "string" && id !== "" && secret !== "" ? { id, secret } : undefined;
}

function storedSession(): Stored | undefined {
  const raw = readJson(SESSION_KEY);
  if (!isJsonObject(raw)) return undefined;
  const gpu = raw["gpu"];
  if (typeof raw["gateway"] !== "string" || typeof raw["session_id"] !== "string" || raw["provider"] !== "modal" || (gpu !== null && typeof gpu !== "string")) return undefined;
  return { gateway: raw["gateway"], session_id: raw["session_id"], provider: "modal", gpu };
}

const describe = (e: unknown): string =>
  e instanceof TypeError ? `the gateway at ${gateway()} is unreachable` : e instanceof Error ? e.message : String(e);

export async function connect(token: Token, gpu: string | null, leaseS: number): Promise<void> {
  if (phase.kind !== "disconnected") throw new Error(`connect() while ${phase.kind}`);
  writeJson(TOKEN_KEY, token);
  setPhase({ kind: "connecting", gpu, step: "asking the gateway" });
  note(`connect: modal, gpu ${gpu ?? "none"}, length ${String(leaseS / 60)} min, gateway ${gateway()}`);
  try {
    const { id, status } = await createSession(gateway(), token, gpu, leaseS);
    const cancelledWhileCreating = currentPhase().kind !== "connecting";
    if (cancelledWhileCreating) {
      note(`session ${id} created after Cancel; ending it`);
      await endSession(gateway(), id, token);
      return;
    }
    const stored: Stored = { gateway: gateway(), session_id: id, provider: "modal", gpu };
    writeJson(SESSION_KEY, stored);
    note(`session ${id} created`);
    follow(stored, token, status);
  } catch (cause) {
    note(`connect failed: ${describe(cause)}`, "error");
    setPhase({ kind: "disconnected", failure: describe(cause) });
  }
}

export async function resume(): Promise<void> {
  const stored = storedSession();
  const token = savedToken();
  if (stored?.gateway !== gateway()) return;
  if (token === undefined) { writeJson(SESSION_KEY, null); return; }
  setPhase({ kind: "connecting", gpu: stored.gpu, step: "reattaching" });
  note(`reattaching to session ${stored.session_id}`);
  try {
    const status = await getSession(gateway(), stored.session_id, token);
    if (status === "gone") { end(undefined, "the gateway no longer knows this session"); return; }
    follow(stored, token, status);
  } catch (cause) {
    note(`reattach failed: ${describe(cause)}`, "error");
    setPhase({ kind: "disconnected", failure: `${describe(cause)}; your session may still be running` });
  }
}

function follow(stored: Stored, token: Token, status: Status): void {
  live?.close();
  const close = subscribe(gateway(), stored.session_id, token, receive, () => { void recheck(); }, (e) => { end(undefined, e.message); });
  live = { stored, token, close };
  apply(status);
}

function receive(event: GatewayEvent): void {
  if (event.kind === "status") {
    const s = event.status;
    const failed = s.state === "ended";
    append({ t: event.t, source: "gateway", kind: failed ? "error" : "step", text: `status: ${s.state}${s.state === "ended" ? ` (${s.reason})` : ""}` });
    apply(event.status);
    return;
  }
  append({ t: event.t, source: event.source, kind: event.kind, text: event.text });
  if (event.kind === "step" && phase.kind === "connecting") setPhase({ ...phase, step: event.text });
}

function apply(status: Status): void {
  if (live === undefined) return;
  if (status.state === "ended") { end(status.reason, REASONS[status.reason]); return; }
  if (status.state === "booting" || attaching) return;
  if (phase.kind === "connected") { setPhase({ ...phase, leaseUntil: status.leaseUntil, ceiling: status.ceiling }); return; }
  const kernel = status.kernel;
  attaching = true;
  setPhase({ kind: "connecting", gpu: status.gpu, step: "starting the kernel" });
  attach(kernel).then(() => {
    note(`kernel attached (${kernel.url})`);
    if (live !== undefined) setPhase({ kind: "connected", id: live.stored.session_id, gpu: status.gpu, startedAt: status.startedAt, leaseUntil: status.leaseUntil, ceiling: status.ceiling });
  }, (cause: unknown) => {
    note(`kernel attach failed: ${describe(cause)}`, "error");
    void recheck();
  }).finally(() => { attaching = false; });
}

async function recheck(): Promise<void> {
  const current = live;
  if (current === undefined) return;
  try {
    const status = await getSession(gateway(), current.stored.session_id, current.token);
    if (status === "gone") { end(undefined, "the gateway no longer knows this session"); return; }
    if (status.state !== "running" || Date.now() - lastReattach < REATTACH_GAP_MS) { apply(status); return; }
    lastReattach = Date.now();
    note("kernel connection lost; reattaching");
    setPhase({ kind: "connecting", gpu: status.gpu, step: "reattaching to the kernel" });
    apply(status);
  } catch (cause) {
    end(undefined, `lost the gateway: ${describe(cause)}`);
  }
}

function end(reason: EndedReason | undefined, failure: string | undefined): void {
  live?.close();
  live = undefined;
  detach();
  writeJson(SESSION_KEY, null);
  if (reason !== undefined || failure !== undefined) note(`session ended${reason ? ` (${reason})` : ""}${failure ? `: ${failure}` : ""}`, failure !== undefined ? "error" : "step");
  setPhase({ kind: "disconnected", failure });
}

export async function extend(until: number): Promise<void> {
  const current = live;
  if (current === undefined || phase.kind !== "connected") throw new Error(`extend() while ${phase.kind}`);
  const status = await extendSession(gateway(), current.stored.session_id, current.token, until);
  if (status.state === "ended") { note("extend: the session had already ended"); apply(status); return; }
  const clamped = status.leaseUntil < until ? ` (capped at the ceiling, ${new Date(status.ceiling * 1000).toLocaleTimeString()})` : "";
  note(`lease extended: asked until ${new Date(until * 1000).toLocaleTimeString()}, now ends ${new Date(status.leaseUntil * 1000).toLocaleTimeString()}${clamped}`);
  apply(status);
}

export async function disconnect(): Promise<void> {
  const current = live;
  if (current === undefined) { end(undefined, undefined); return; }
  live = undefined;
  current.close();
  note(`ending session ${current.stored.session_id}`);
  try {
    await endSession(gateway(), current.stored.session_id, current.token);
  } catch (cause) {
    note(`end failed: ${describe(cause)}; the session stops when its length runs out`, "error");
  }
  end(undefined, undefined);
}

export async function signOut(): Promise<void> {
  await disconnect();
  writeJson(TOKEN_KEY, null);
  note("signed out: token forgotten");
}

onKernelState((state) => { if (state === "lost" && phase.kind === "connected") void recheck(); });

