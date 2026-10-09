// The page's Connect session: one state machine, the token and session in localStorage, the event log.
//
//   disconnected --connect()--> connecting --status running + kernel attached--> connected
//        ^                          |                                               |
//        +---- ended / disconnect() / failure (the reason stays on `failure`) ------+
//
// Storage (box/CONTRACT-gateway.md, "Browser storage"):
//   connect.token.modal = {id, secret}                        until Sign out
//   connect.session     = {gateway, session_id, provider, gpu} while a session lives; any opted-in page reattaches
import { createSession, endSession, getSession, subscribe } from "./gateway";
import type { EndedReason, GatewayEvent, Status, Token } from "./gateway";
import { attach, detach, onKernelState } from "./kernel";

export type Phase =
  | { kind: "disconnected"; failure: string | undefined }
  | { kind: "connecting"; gpu: string | null; step: string }
  | { kind: "connected"; id: string; gpu: string | null; startedAt: number; deadline: number };

export interface LogLine {
  t: number; // unix seconds
  source: "gateway" | "machine" | "page";
  kind: "step" | "log" | "error"; // progress, machine output, something went wrong
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
const MAX_LOG = 2000; // lines kept for the drawer; older ones are dropped (it says so)
const REATTACH_GAP_MS = 10_000;

const REASONS: Record<EndedReason, string | undefined> = {
  stopped: undefined,
  deadline: "the session reached its time limit",
  idle: "the session was idle too long and was stopped",
  lease_lost: "the session lost its lease (another tab or the gateway ended it)",
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
let attaching = false; // a status replayed while the kernel attaches must not start a second attach

// The gateway's base URL: <connect-pill data-gateway> (build_page.py --gateway-url), or ?gateway= for dev.
function gatewayUrl(): string {
  const fromQuery = new URLSearchParams(location.search).get("gateway");
  const url = fromQuery !== null && fromQuery !== "" ? fromQuery : document.querySelector("connect-pill")?.getAttribute("data-gateway") ?? "";
  if (url === "") throw new Error("connect: no gateway URL (<connect-pill data-gateway> or ?gateway=)");
  return url.replace(/\/$/, "");
}
let gatewayCache: string | undefined;
const gateway = (): string => (gatewayCache ??= gatewayUrl());

export const currentPhase = (): Phase => phase;
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

// ---- storage (it can be blocked: then nothing is remembered, and Connect still works for this page) ----

const readJson = (key: string): unknown => {
  try { return JSON.parse(localStorage.getItem(key) ?? "null"); } catch { return null; }
};
const writeJson = (key: string, value: unknown): void => {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch { /* storage blocked */ }
};

export function savedToken(): Token | undefined {
  const raw = readJson(TOKEN_KEY);
  if (typeof raw !== "object" || raw === null || !("id" in raw) || !("secret" in raw)) return undefined;
  const { id, secret } = raw;
  return typeof id === "string" && typeof secret === "string" && id !== "" && secret !== "" ? { id, secret } : undefined;
}

function storedSession(): Stored | undefined {
  const raw = readJson(SESSION_KEY);
  if (typeof raw !== "object" || raw === null) return undefined;
  const r: Partial<Record<string, unknown>> = { ...raw };
  const gpu = r["gpu"];
  if (typeof r["gateway"] !== "string" || typeof r["session_id"] !== "string" || r["provider"] !== "modal" || (gpu !== null && typeof gpu !== "string")) return undefined;
  return { gateway: r["gateway"], session_id: r["session_id"], provider: "modal", gpu };
}

// ---- transitions ----

const describe = (e: unknown): string =>
  e instanceof TypeError ? `the gateway at ${gateway()} is unreachable` : e instanceof Error ? e.message : String(e);

export async function connect(token: Token, gpu: string | null): Promise<void> {
  if (phase.kind !== "disconnected") throw new Error(`connect() while ${phase.kind}`);
  writeJson(TOKEN_KEY, token);
  setPhase({ kind: "connecting", gpu, step: "asking the gateway" });
  note(`connect: modal, gpu ${gpu ?? "none"}, gateway ${gateway()}`);
  try {
    const { id, status } = await createSession(gateway(), token, gpu);
    if (currentPhase().kind !== "connecting") { // cancelled while the gateway was creating it
      note(`session ${id} created after Cancel; ending it`);
      await endSession(gateway(), id, token);
      return;
    }
    const stored: Stored = { gateway: gateway(), session_id: id, provider: "modal", gpu };
    writeJson(SESSION_KEY, stored);
    note(`session ${id} created`);
    follow(stored, token, status);
  } catch (e) {
    note(`connect failed: ${describe(e)}`, "error");
    setPhase({ kind: "disconnected", failure: describe(e) });
  }
}

// A session from an earlier page or tab: reattach if it still runs, forget it if it ended.
export async function resume(): Promise<void> {
  const stored = storedSession();
  const token = savedToken();
  if (stored?.gateway !== gateway()) return; // none, or another gateway's (left alone)
  if (token === undefined) { writeJson(SESSION_KEY, null); return; }
  setPhase({ kind: "connecting", gpu: stored.gpu, step: "reattaching" });
  note(`reattaching to session ${stored.session_id}`);
  try {
    const status = await getSession(gateway(), stored.session_id, token);
    if (status === "gone") { end(undefined, "the gateway no longer knows this session"); return; }
    follow(stored, token, status);
  } catch (e) {
    note(`reattach failed: ${describe(e)}`, "error");
    setPhase({ kind: "disconnected", failure: `${describe(e)}; your session may still be running` });
  }
}

function follow(stored: Stored, token: Token, status: Status): void {
  live?.close();
  const close = subscribe(gateway(), stored.session_id, token, receive, () => { void recheck(); });
  live = { stored, token, close };
  apply(status);
}

function receive(event: GatewayEvent): void {
  if (event.kind === "status") {
    const s = event.status;
    const failed = s.state === "ended" && s.reason !== "stopped";
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
  if (status.state === "booting" || phase.kind === "connected" || attaching) return;
  const kernel = status.kernel;
  attaching = true;
  setPhase({ kind: "connecting", gpu: status.gpu, step: "starting the kernel" });
  attach(kernel).then(() => {
    note(`kernel attached (${kernel.url})`);
    if (live !== undefined) setPhase({ kind: "connected", id: live.stored.session_id, gpu: status.gpu, startedAt: status.startedAt, deadline: status.deadline });
  }, (e: unknown) => {
    note(`kernel attach failed: ${describe(e)}`, "error");
    void recheck();
  }).finally(() => { attaching = false; });
}

// The event stream broke or the kernel stopped answering: ask the gateway what happened.
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
  } catch (e) {
    end(undefined, `lost the gateway: ${describe(e)}`);
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

export async function disconnect(): Promise<void> {
  const current = live;
  if (current === undefined) { end(undefined, undefined); return; }
  note(`ending session ${current.stored.session_id}`);
  try {
    await endSession(gateway(), current.stored.session_id, current.token);
  } catch (e) {
    // The machine may outlive this (the gateway reaps it at its deadline); say so rather than pretend.
    note(`end failed: ${describe(e)}; the session stops at its deadline`, "error");
  }
  end(undefined, undefined);
}

export async function signOut(): Promise<void> {
  await disconnect();
  writeJson(TOKEN_KEY, null);
  note("signed out: token forgotten");
}

onKernelState((state) => { if (state === "lost" && phase.kind === "connected") void recheck(); });

