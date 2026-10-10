// The connected session's Jupyter kernel (box/CONTRACT-gateway.md "Cells"): one kernel per session, at
// status.kernel.url with its token. Cells and embeds run code here; session.ts attaches and detaches it.
//
// Public API (stable; the nn-fit remote backend imports it):
//   runCode(code, onStdout, onStderr?) -> Promise<RunResult>   one execute_request; output streams as it arrives
//   interrupt()                        -> Promise<void>        Jupyter interrupt (a running cell ends with KeyboardInterrupt)
//   kernelState()                      -> KernelState          "off" until connected
//   onKernelState(listener)            -> unsubscribe          called on every change
//   runJob(id, argv, cwd, onOutput)    -> Promise<JobResult>   a background subprocess (jobs.py): the kernel is free
//                                                              as soon as it starts; output streams until it exits
//   killJob(id)                        -> Promise<void>        SIGTERM to the job's process group
//   kernelAddress()                    -> KernelAddress | undefined  for the Contents API (connect/contents.ts)
//
// Every bundle on a page gets its own copy of this module (esbuild bundles page.ts and each embed separately), so
// the one live kernel lives in a window slot: whichever copy runs first creates it, every copy uses it.
//
// Wire: Jupyter Server REST + the kernel websocket (protocol 5.3). The token goes in the query string: a browser
// can't set headers on a WebSocket, and query-only auth keeps fetches simple (no CORS preflight).

import JOBS_PY from "./jobs.py";
import { isJsonObject } from "../json";
import type { JsonObject } from "../json";

export interface KernelAddress {
  url: string;
  token: string;
}

export type RunResult =
  | { status: "ok" }
  | { status: "error"; ename: string; evalue: string; traceback: string } // a Python exception (ANSI stripped)
  | { status: "aborted"; reason: string }; // never ran or never finished: not connected, connection lost, kernel died

// A background job ends with its exit code (negative: killed by that signal), or it never started (the launching
// cell raised), or the page lost it (socket dropped, kernel restarted: the process may still be running).
export type JobResult = { status: "exited"; exit: number } | Exclude<RunResult, { status: "ok" }>;

const JOB_MIME = "application/vnd.blogs.job+json"; // jobs.py's end-of-job marker

// off: no session. attaching: finding/starting the kernel. idle/busy: ready (busy = a runCode is in flight).
// lost: the kernel stopped answering; session.ts decides whether the session is gone.
export type KernelState = "off" | "attaching" | "idle" | "busy" | "lost";

const KEEPALIVE_MS = 30_000; // traffic on the tunnel (Modal's idle timeout counts it) + notices a dead socket
const REPLY_TIMEOUT_MS = 30_000;
const ANSI = /\x1b\[[0-9;]*[A-Za-z]/g; // eslint-disable-line no-control-regex

// One message off the websocket, parsed (it crossed the network).
interface Msg {
  type: string;
  parent: string | undefined;
  channel: string;
  content: JsonObject;
}

function parseMsg(raw: unknown): Msg {
  if (!isJsonObject(raw) || !isJsonObject(raw["header"]) || typeof raw["header"]["msg_type"] !== "string" || !isJsonObject(raw["content"])) {
    throw new Error(`kernel websocket: expected a Jupyter message, got ${JSON.stringify(raw).slice(0, 200)}`);
  }
  const parent = isJsonObject(raw["parent_header"]) && typeof raw["parent_header"]["msg_id"] === "string" ? raw["parent_header"]["msg_id"] : undefined;
  return { type: raw["header"]["msg_type"], parent, channel: typeof raw["channel"] === "string" ? raw["channel"] : "", content: raw["content"] };
}

const text = (content: JsonObject, key: string): string => {
  const v = content[key];
  return typeof v === "string" ? v : "";
};

// The content of an execute_request (the only request the page sends with a non-empty content).
interface ExecuteRequest {
  code: string; silent: boolean; store_history: boolean; user_expressions: Record<string, never>;
  allow_stdin: boolean; stop_on_error: boolean;
}

interface Gone { gone: string } // the socket closed or the kernel died before a reply
type Handler = (msg: Msg | Gone) => void;

class Kernel {
  state: KernelState = "off";
  address: KernelAddress | undefined; // read by kernelAddress() (the Contents API needs the same URL + token)
  private id: string | undefined;
  private ws: WebSocket | undefined;
  private keepalive: ReturnType<typeof setInterval> | undefined;
  private running = 0;
  private readonly pending = new Map<string, Handler>();
  private readonly listeners = new Set<(state: KernelState) => void>();
  private readonly client = crypto.randomUUID();

  subscribe(listener: (state: KernelState) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private set(state: KernelState): void {
    if (state === this.state) return;
    this.state = state;
    for (const listener of this.listeners) listener(state);
  }

  private api(path: string): string {
    if (this.address === undefined) throw new Error("kernel: no address (not attached)");
    return `${this.address.url}${path}?token=${encodeURIComponent(this.address.token)}`;
  }

  // Find the session's kernel (another page of this session may have started it) or start one; open its socket.
  async attach(address: KernelAddress): Promise<void> {
    if (this.address?.url === address.url && this.address.token === address.token && this.ws?.readyState === WebSocket.OPEN) return;
    this.detach();
    this.address = address;
    this.set("attaching");
    try {
      const listed: unknown = await (await fetch(this.api("/api/kernels"))).json();
      const first = Array.isArray(listed) ? listed.find(isJsonObject) : undefined;
      // No Content-Type: a text/plain body keeps this a simple request; Jupyter parses it as JSON anyway.
      const kernel: unknown = first ?? await (await fetch(this.api("/api/kernels"), { method: "POST", body: JSON.stringify({ name: "python3" }) })).json();
      if (!isJsonObject(kernel) || typeof kernel["id"] !== "string") throw new Error(`kernel: /api/kernels gave no id: ${JSON.stringify(kernel)}`);
      this.id = kernel["id"];
      await this.open();
      this.set("idle");
    } catch (cause) {
      this.set("lost");
      throw cause;
    }
  }

  detach(): void {
    const ws = this.ws;
    this.ws = undefined;
    clearInterval(this.keepalive);
    ws?.close();
    this.abortAll("disconnected");
    this.address = undefined;
    this.id = undefined;
    this.running = 0;
    this.set("off");
  }

  private open(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.id === undefined) throw new Error("kernel: open() before a kernel id");
      const ws = new WebSocket(this.api(`/api/kernels/${this.id}/channels`).replace(/^http/, "ws"));
      this.ws = ws;
      ws.onmessage = (e) => { this.receive(parseMsg(JSON.parse(String(e.data)))); };
      ws.onclose = () => {
        if (this.ws !== ws) return; // detached on purpose
        clearInterval(this.keepalive);
        this.abortAll("the connection to the kernel dropped");
        this.set("lost");
        reject(new Error("kernel websocket closed"));
      };
      ws.onopen = () => {
        // The kernel answers kernel_info once it is really up.
        this.request("kernel_info_request").then(() => {
          clearInterval(this.keepalive);
          this.keepalive = setInterval(() => { this.ping(); }, KEEPALIVE_MS);
          resolve();
        }, reject);
      };
    });
  }

  // On the control channel: a busy kernel (a long cell, e.g. nn-fit's remote run) doesn't answer the shell
  // channel until the cell ends, so a shell ping timed out and closed the socket ~30-60 s into any longer run.
  // ipykernel answers kernel_info on control while busy (7.4 on the relay's machine: 0.1 s).
  private ping(): void {
    this.request("kernel_info_request", "control").catch(() => { this.ws?.close(); });
  }

  private send(type: string, content: ExecuteRequest | Record<string, never>, channel = "shell"): string {
    if (this.ws?.readyState !== WebSocket.OPEN) throw new Error("kernel: socket not open");
    const id = crypto.randomUUID();
    this.ws.send(JSON.stringify({
      header: { msg_id: id, msg_type: type, username: "reader", session: this.client, date: new Date().toISOString(), version: "5.3" },
      parent_header: {}, metadata: {}, content, channel, buffers: [],
    }));
    return id;
  }

  // A request answered by one reply on the same channel, or rejected after REPLY_TIMEOUT_MS / when the socket goes.
  private request(type: string, channel: "shell" | "control" = "shell"): Promise<Msg> {
    return new Promise((resolve, reject) => {
      const id = this.send(type, {}, channel);
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`kernel: no ${type} reply in ${String(REPLY_TIMEOUT_MS)}ms`)); }, REPLY_TIMEOUT_MS);
      this.pending.set(id, (msg) => {
        if ("gone" in msg) { clearTimeout(timer); this.pending.delete(id); reject(new Error(msg.gone)); return; }
        if (msg.channel !== channel) return;
        clearTimeout(timer);
        this.pending.delete(id);
        resolve(msg);
      });
    });
  }

  private receive(msg: Msg): void {
    if (msg.type === "status") {
      const s = text(msg.content, "execution_state");
      if (s === "restarting" || s === "dead") this.abortAll("the kernel crashed and restarted (its variables are gone)");
    }
    if (msg.parent !== undefined) this.pending.get(msg.parent)?.(msg);
  }

  private abortAll(reason: string): void {
    for (const handler of [...this.pending.values()]) handler({ gone: reason });
    this.pending.clear();
  }

  run(code: string, onStdout: (text: string) => void, onStderr: (text: string) => void): Promise<RunResult> {
    if (this.state !== "idle" && this.state !== "busy") return Promise.resolve({ status: "aborted", reason: "not connected" });
    this.running += 1;
    this.set("busy");
    return new Promise<RunResult>((resolve) => {
      let reply: RunResult | undefined;
      let idle = false;
      let id: string;
      try {
        id = this.send("execute_request", { code, silent: false, store_history: true, user_expressions: {}, allow_stdin: false, stop_on_error: true });
      } catch {
        resolve({ status: "aborted", reason: "the connection to the kernel is closed" });
        return;
      }
      const finish = (result: RunResult): void => {
        this.pending.delete(id);
        resolve(result);
      };
      this.pending.set(id, (msg) => {
        if ("gone" in msg) { finish({ status: "aborted", reason: msg.gone }); return; }
        const c = msg.content;
        if (msg.type === "stream") (text(c, "name") === "stderr" ? onStderr : onStdout)(text(c, "text"));
        else if ((msg.type === "execute_result" || msg.type === "display_data") && isJsonObject(c["data"])) {
          const plain = c["data"]["text/plain"];
          onStdout(typeof plain === "string" ? `${plain}\n` : `[${Object.keys(c["data"]).join(", ")} output not shown]\n`);
        } else if (msg.type === "execute_reply") reply = parseReply(c);
        else if (msg.type === "status" && text(c, "execution_state") === "idle") idle = true;
        if (reply !== undefined && idle) finish(reply);
      });
    }).finally(() => {
      this.running -= 1;
      if (this.running === 0 && this.state === "busy") this.set("idle");
    });
  }

  // A job: one execute_request starts the subprocess (installing jobs.py first if this kernel lacks it). Unlike
  // run(), the handler outlives the reply: the job's output keeps arriving under this request's msg_id until the
  // JOB_MIME marker. The kernel counts as busy only until the reply (the job itself doesn't occupy it).
  job(id: string, argv: string[], cwd: string, onOutput: (text: string) => void): Promise<JobResult> {
    if (this.state !== "idle" && this.state !== "busy") return Promise.resolve({ status: "aborted", reason: "not connected" });
    const code = `if "_blogs_jobs" not in globals():\n    exec(${JSON.stringify(JOBS_PY)})\n_blogs_jobs.start(${JSON.stringify(id)}, ${JSON.stringify(argv)}, ${JSON.stringify(cwd)})`;
    this.running += 1;
    this.set("busy");
    let replied = false;
    const done = (): void => {
      if (replied) return;
      replied = true;
      this.running -= 1;
      if (this.running === 0 && this.state === "busy") this.set("idle");
    };
    return new Promise<JobResult>((resolve) => {
      let msgId: string;
      try {
        msgId = this.send("execute_request", { code, silent: false, store_history: false, user_expressions: {}, allow_stdin: false, stop_on_error: false });
      } catch {
        done();
        resolve({ status: "aborted", reason: "the connection to the kernel is closed" });
        return;
      }
      const finish = (result: JobResult): void => {
        done();
        this.pending.delete(msgId);
        resolve(result);
      };
      this.pending.set(msgId, (msg) => {
        if ("gone" in msg) { finish({ status: "aborted", reason: msg.gone }); return; }
        const c = msg.content;
        if (msg.type === "stream") onOutput(text(c, "text"));
        else if (msg.type === "display_data" && isJsonObject(c["data"]) && isJsonObject(c["data"][JOB_MIME])) {
          const marker = c["data"][JOB_MIME];
          if (typeof marker["exit"] !== "number") throw new Error(`kernel: job marker without an exit code: ${JSON.stringify(marker)}`);
          finish({ status: "exited", exit: marker["exit"] });
        } else if (msg.type === "execute_reply") {
          const reply = parseReply(c);
          if (reply.status !== "ok") finish(reply); // the job never started
          else done();
        }
      });
    });
  }

  async interrupt(): Promise<void> {
    if (this.id === undefined) return;
    const res = await fetch(this.api(`/api/kernels/${this.id}/interrupt`), { method: "POST" });
    if (!res.ok) throw new Error(`kernel: interrupt answered ${String(res.status)}`);
  }
}

function parseReply(c: JsonObject): RunResult {
  const status = text(c, "status");
  if (status === "ok") return { status: "ok" };
  if (status === "aborted") return { status: "aborted", reason: "the kernel skipped it (an earlier cell failed)" };
  const tb = Array.isArray(c["traceback"]) ? c["traceback"].filter((l): l is string => typeof l === "string").join("\n") : "";
  return { status: "error", ename: text(c, "ename"), evalue: text(c, "evalue"), traceback: tb.replace(ANSI, "") };
}

declare global {
  interface Window {
    blogsConnectKernel?: Kernel; // the shared slot (see the top of this file)
  }
}
const kernel: Kernel = (window.blogsConnectKernel ??= new Kernel());

export const runCode = (code: string, onStdout: (text: string) => void, onStderr: (text: string) => void = onStdout): Promise<RunResult> =>
  kernel.run(code, onStdout, onStderr);
export const interrupt = (): Promise<void> => kernel.interrupt();
export const runJob = (id: string, argv: string[], cwd: string, onOutput: (text: string) => void): Promise<JobResult> =>
  kernel.job(id, argv, cwd, onOutput);
export async function killJob(id: string): Promise<void> {
  const result = await kernel.run(`_blogs_jobs.kill(${JSON.stringify(id)})`, () => undefined, () => undefined);
  if (result.status !== "ok") throw new Error(`kill ${id}: ${result.status === "error" ? `${result.ename}: ${result.evalue}` : result.reason}`);
}
export const kernelAddress = (): KernelAddress | undefined => kernel.address;
export const kernelState = (): KernelState => kernel.state;
export const onKernelState = (listener: (state: KernelState) => void): (() => void) => kernel.subscribe(listener);

// session.ts only: attach when the session is running, detach when it ends or the reader disconnects.
export const attach = (address: KernelAddress): Promise<void> => kernel.attach(address);
export const detach = (): void => { kernel.detach(); };
