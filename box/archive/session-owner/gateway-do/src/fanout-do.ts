// Variant (C) fanout: the machine owns the session (its supervisor: lease, deadline, idleness); this
// Durable Object only fans its events out. It never decides anything about the session and never
// holds the reader's token (only a digest, to check who reads). GET /sessions/{id} and /end go to the
// Python relay (variant A) in the Worker; the kernel is the Modal tunnel, direct (status.kernel).
//
// Everything here is rebuildable: lose the DO and the session runs on; readers only lose the replay.

import { Hub } from "./hub";
import { type GatewayEvent } from "./types";

export class FanoutDO extends Hub {
  // The Worker created the session on the relay: remember who may read it.
  async created(digest: string): Promise<void> {
    this.setMeta("digest", digest);
  }

  // A status from the relay (boot) or the forwarder (the session's end): passed through as said.
  // Note: a running status carries the kernel's {url, token}; that token (derived per session, not the
  // reader's Modal token) is in the ring buffer for as long as the DO keeps it.
  protected async onStatus(event: Extract<GatewayEvent, { kind: "status" }>): Promise<void> {
    this.publish(event);
    if (event.status.state === "running") this.watch(true);
    if (event.status.state === "ended") this.watch(false);
  }

  // Not the DO's call whether the session ended: say what it sees; GET /sessions/{id} asks the machine.
  protected async onSilent(silentFor: number): Promise<void> {
    this.step(`no word from the machine for ${silentFor.toFixed(0)} s: it may be gone (the relay knows: GET /sessions/{id})`);
  }
}
