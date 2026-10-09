// Shapes from box/CONTRACT-gateway.md (v0). Kept in one place so variants (B) and (C) share them.

export type State = "booting" | "running" | "ended";
export type EndReason = "stopped" | "deadline" | "idle" | "lease_lost" | "boot_failed" | "machine_lost";

export interface Status {
  state: State;
  gpu: string | null;
  started_at: number | null; // epoch ms
  deadline: number | null; // epoch ms
  reason?: EndReason;
  kernel?: { url: string; token: string };
}

export type GatewayEvent =
  | { t: number; kind: "step"; source: "gateway" | "machine"; text: string }
  | { t: number; kind: "log"; source: "machine"; stream: "stdout" | "stderr"; text: string }
  | { t: number; kind: "status"; status: Status };

export interface Env {
  SESSION: DurableObjectNamespace;
  RING_SIZE: string;
  HEARTBEAT_MS: string;
  // If set, producer routes (machine push, upstream, deadline) require header X-Machine-Key.
  MACHINE_KEY?: string;
}
