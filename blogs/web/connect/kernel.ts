// The connected session's Jupyter kernel (box/CONTRACT-gateway.md "Cells"): one kernel per session, at
// status.kernel.url with its token. Cells and embeds run code here; session.ts attaches and detaches it.
//
// Public API (stable; the nn-fit remote backend imports it):
//   runCode(code, onStdout, onStderr?) -> Promise<RunResult>   one execute_request; output streams as it arrives
//   interrupt()                        -> Promise<void>        Jupyter interrupt (a running cell ends with KeyboardInterrupt)
//   kernelState()                      -> KernelState          "off" until connected
//   onKernelState(listener)            -> unsubscribe          called on every change
//
// Every bundle on a page gets its own copy of this module (esbuild bundles page.ts and each embed separately), so
// the one live kernel lives in a window slot: whichever copy runs first creates it, every copy uses it.
//
// Wire: Jupyter Server REST + the kernel websocket (protocol 5.3). The token goes in the query string: a browser
// can't set headers on a WebSocket, and query-only auth keeps fetches simple (no CORS preflight).

export interface KernelAddress {
  url: string;
  token: string;
}

export type RunResult =
  | { status: "ok" }
  | { status: "error"; ename: string; evalue: string; traceback: string } // a Python exception (ANSI stripped)
  | { status: "aborted"; reason: string }; // never ran or never finished: not connected, connection lost, kernel died

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
  content: Record<string, unknown>;
}

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

function parseMsg(raw: unknown): Msg {
  if (!isRecord(raw) || !isRecord(raw["header"]) || typeof raw["header"]["msg_type"] !== "string" || !isRecord(raw["content"])) {
    throw new Error(`kernel websocket: expected a Jupyter message, got ${JSON.stringify(raw).slice(0, 200)}`);
  }
  const parent = isRecord(raw["parent_header"]) && typeof raw["parent_header"]["msg_id"] === "string" ? raw["parent_header"]["msg_id"] : undefined;
  return { type: raw["header"]["msg_type"], parent, channel: typeof raw["channel"] === "string" ? raw["channel"] : "", content: raw["content"] };
}

const text = (content: Record<string, unknown>, key: string): string => {
  const v = content[key];
  return typeof v === "string" ? v : "";
};

interface Gone { gone: string } // the socket closed or the kernel died before a reply
type Handler = (msg: Msg | Gone) => void;

class Kernel {
  state: KernelState = "off";
  private address: KernelAddress | undefined;
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
      const first = Array.isArray(listed) ? listed.find(isRecord) : undefined;
      // No Content-Type: a text/plain body keeps this a simple request; Jupyter parses it as JSON anyway.
      const kernel: unknown = first ?? await (await fetch(this.api("/api/kernels"), { method: "POST", body: JSON.stringify({ name: "python3" }) })).json();
      if (!isRecord(kernel) || typeof kernel["id"] !== "string") throw new Error(`kernel: /api/kernels gave no id: ${JSON.stringify(kernel)}`);
      this.id = kernel["id"];
      await this.open();
      this.set("idle");
    } catch (e) {
      this.set("lost");
      throw e;
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

  private ping(): void {
    this.request("kernel_info_request").catch(() => { this.ws?.close(); });
  }

  private send(type: string, content: Record<string, unknown>, channel = "shell"): string {
    if (this.ws?.readyState !== WebSocket.OPEN) throw new Error("kernel: socket not open");
    const id = crypto.randomUUID();
    this.ws.send(JSON.stringify({
      header: { msg_id: id, msg_type: type, username: "reader", session: this.client, date: new Date().toISOString(), version: "5.3" },
      parent_header: {}, metadata: {}, content, channel, buffers: [],
    }));
    return id;
  }

  // A shell request answered by one shell reply, or rejected after REPLY_TIMEOUT_MS / when the socket goes.
  private request(type: string): Promise<Msg> {
    return new Promise((resolve, reject) => {
      const id = this.send(type, {});
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`kernel: no ${type} reply in ${String(REPLY_TIMEOUT_MS)}ms`)); }, REPLY_TIMEOUT_MS);
      this.pending.set(id, (msg) => {
        if ("gone" in msg) { clearTimeout(timer); this.pending.delete(id); reject(new Error(msg.gone)); return; }
        if (msg.channel !== "shell") return;
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
        else if ((msg.type === "execute_result" || msg.type === "display_data") && isRecord(c["data"])) {
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

  async interrupt(): Promise<void> {
    if (this.id === undefined) return;
    const res = await fetch(this.api(`/api/kernels/${this.id}/interrupt`), { method: "POST" });
    if (!res.ok) throw new Error(`kernel: interrupt answered ${String(res.status)}`);
  }
}

function parseReply(c: Record<string, unknown>): RunResult {
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
export const kernelState = (): KernelState => kernel.state;
export const onKernelState = (listener: (state: KernelState) => void): (() => void) => kernel.subscribe(listener);

// session.ts only: attach when the session is running, detach when it ends or the reader disconnects.
export const attach = (address: KernelAddress): Promise<void> => kernel.attach(address);
export const detach = (): void => { kernel.detach(); };
