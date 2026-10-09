// Variant (B) do-owns: this Durable Object is the session (vmux style). It holds the canonical status,
// the event ring, the reader's Modal token (until the session ends: then it is deleted), the
// deadline (its alarm), and a token-gated proxy to the kernel. Machines are made and ended by the
// Python relay (box SDK), which this DO calls with the token it holds. The machine's supervisor still
// ends the session on idleness (connections to Jupyter: this proxy's are spliced sockets the DO can't
// see close) and at its own, later deadline (a backstop); it says so through the forwarder.
//
// meta (beyond hub.ts's): id, origin (the gateway's public base, for status.kernel.url), status,
// token (the reader's {id, secret}), kernel_token (what the browser shows the proxy), upstream (the
// Jupyter {url, token} behind the proxy), retry_at (a failed deadline end is retried then).

import { Hub, json } from "./hub";
import { proxy } from "./proxy";
import { relayCall } from "./relay";
import { now, parseStatus, type EndReason, type GatewayEvent, type Kernel, type ModalToken, type Status } from "./types";

const RETRY_S = 30; // a deadline end the relay did not confirm is tried again after this
const KERNEL_TOKEN_BYTES = 24;

export class OwnerDO extends Hub {
  // The Worker created the machine on the relay; from here this DO owns the session.
  async created(a: { id: string; origin: string; token: ModalToken; digest: string; gpu: string | null }): Promise<Status> {
    const kernelToken = [...crypto.getRandomValues(new Uint8Array(KERNEL_TOKEN_BYTES))].map((b) => b.toString(16).padStart(2, "0")).join("");
    const t = now();
    this.setMeta("id", a.id);
    this.setMeta("origin", a.origin);
    this.setMeta("token", a.token);
    this.setMeta("digest", a.digest);
    this.setMeta("kernel_token", kernelToken);
    const status = this.setStatus({ state: "booting", gpu: a.gpu, started_at: t, deadline: t + Number(this.env.DEADLINE_S) });
    await this.arm();
    return status;
  }

  async get(auth: string): Promise<{ code: number; body: unknown }> {
    const denied = await this.denied(auth);
    if (denied) return { code: denied.status, body: await denied.json() };
    return { code: 200, body: { session_id: this.meta<string>("id"), status: this.status() } };
  }

  async end(auth: string): Promise<{ code: number; body: unknown }> {
    const denied = await this.denied(auth);
    if (denied) return { code: denied.status, body: await denied.json() };
    const ended = await this.endMachine("stopped");
    if (ended === null) return { code: 502, body: { error: "the relay did not confirm the end; the deadline alarm retries" } };
    await this.arm();
    return { code: 200, body: { session_id: this.meta<string>("id"), status: ended } };
  }

  // ---- what the relay and the forwarder say ----

  protected async onStatus(event: Extract<GatewayEvent, { kind: "status" }>): Promise<void> {
    const mine = this.status();
    const said = event.status;
    if (mine.state === "ended") {
      if (said.state === "ended") this.step(`machine says it ended (${said.reason}) after this gateway ended it (${mine.reason})`);
      return;
    }
    if (said.state === "booting") return; // already booting: this DO said so at create
    if (said.state === "running") {
      this.setMeta("upstream", said.kernel);
      const kernel: Kernel = { url: `${this.meta<string>("origin")}/sessions/${this.meta<string>("id")}/kernel`, token: this.meta<string>("kernel_token")! };
      this.setStatus({ state: "running", gpu: mine.gpu, started_at: said.started_at, deadline: mine.deadline, kernel });
      this.watch(true);
      return;
    }
    this.setEnded(said.reason);
  }

  // The machine went quiet: ask the relay (with the token this DO holds) whether it still exists.
  protected async onSilent(silentFor: number): Promise<void> {
    const token = this.meta<ModalToken>("token");
    if (token === null) return; // ended meanwhile
    const r = await relayCall(this.env.RELAY_B, "GET", `/sessions/${this.meta<string>("id")}`, token).catch((e: unknown) => ({ code: 0, body: String(e) }));
    if (r.code === 404) {
      this.step(`no word from the machine for ${silentFor.toFixed(0)} s and the relay finds no machine`);
      this.setEnded("machine_lost");
      return;
    }
    if (r.code === 200) {
      const said = parseStatus((r.body as { status: unknown }).status);
      if (said.state === "ended") this.setEnded(said.reason);
      else this.step(`no word from the machine for ${silentFor.toFixed(0)} s; the relay says it is ${said.state}`);
      return;
    }
    this.step(`no word from the machine for ${silentFor.toFixed(0)} s; asking the relay failed (${r.code}: ${JSON.stringify(r.body).slice(0, 200)})`);
  }

  protected deadlineAt(): number | null {
    const s = this.status();
    return s.state === "ended" ? null : Math.max(s.deadline, this.meta<number>("retry_at") ?? 0);
  }

  protected async onDeadline(): Promise<void> {
    this.step("deadline reached (this gateway's alarm): ending the machine");
    if ((await this.endMachine("deadline")) === null) {
      this.setMeta("retry_at", now() + RETRY_S);
      this.step(`the relay did not confirm the end; retrying in ${RETRY_S} s`);
    }
  }

  // ---- the kernel, through this DO (token-gated; the browser never sees Jupyter's token) ----

  protected async kernel(req: Request, rest: string): Promise<Response> {
    const url = new URL(req.url);
    const upstream = this.meta<Kernel>("upstream");
    const want = this.meta<string>("kernel_token");
    if (upstream === null || want === null) return json({ error: "no kernel: the session is not running" }, 503);
    if (url.searchParams.get("token") !== want) return json({ error: "bad kernel token" }, 403);
    url.searchParams.delete("token"); // Jupyter gets its own, as a header
    return proxy(new Request(url, req), upstream, rest);
  }

  // ---- state ----

  private status(): Status {
    const s = this.meta<Status>("status");
    if (s === null) throw new Error("OwnerDO used before created()");
    return s;
  }

  private setStatus(s: Status): Status {
    this.setMeta("status", s);
    this.publish({ t: now(), kind: "status", status: s });
    return s;
  }

  // The relay ends the machine; null if it could not confirm (the session stays as it was).
  private async endMachine(reason: EndReason): Promise<Status | null> {
    const s = this.status();
    if (s.state === "ended") return s;
    const token = this.meta<ModalToken>("token")!;
    const r = await relayCall(this.env.RELAY_B, "POST", `/sessions/${this.meta<string>("id")}/end`, token).catch((e: unknown) => ({ code: 0, body: String(e) }));
    if (r.code !== 200 && r.code !== 404) {
      this.step(`relay end failed (${r.code}): ${JSON.stringify(r.body).slice(0, 200)}`);
      return null;
    }
    return this.setEnded(reason);
  }

  private setEnded(reason: EndReason): Status {
    const s = this.status();
    if (s.state === "ended") return s;
    this.watch(false);
    this.dropMeta("token", "kernel_token", "upstream", "retry_at"); // the session is over: so is holding its credentials
    return this.setStatus({ state: "ended", gpu: s.gpu, started_at: s.started_at, deadline: s.deadline, reason });
  }
}
