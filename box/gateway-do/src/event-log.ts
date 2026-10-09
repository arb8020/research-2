// Bounded, durable event log in the DO's SQLite. seq is the SSE event id.
// Keeps the newest `capacity` events; older ones are deleted on append.

import type { GatewayEvent } from "./types";

export interface Stored {
  seq: number;
  event: GatewayEvent;
}

export class EventLog {
  constructor(
    private sql: SqlStorage,
    private capacity: number,
  ) {
    sql.exec("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)");
  }

  append(event: GatewayEvent): Stored {
    const row = this.sql
      .exec<{ seq: number }>("INSERT INTO events (data) VALUES (?) RETURNING seq", JSON.stringify(event))
      .one();
    this.sql.exec("DELETE FROM events WHERE seq <= ?", row.seq - this.capacity);
    return { seq: row.seq, event };
  }

  // Events with seq > after, oldest first. `dropped` = how many the client missed because the ring wrapped.
  since(after: number): { events: Stored[]; dropped: number } {
    const events = this.sql
      .exec<{ seq: number; data: string }>("SELECT seq, data FROM events WHERE seq > ? ORDER BY seq", after)
      .toArray()
      .map((r) => ({ seq: r.seq, event: JSON.parse(r.data) as GatewayEvent }));
    const first = events.length ? events[0].seq : this.lastSeq() + 1;
    return { events, dropped: Math.max(0, first - after - 1) };
  }

  lastSeq(): number {
    return this.sql.exec<{ s: number | null }>("SELECT max(seq) AS s FROM events").one().s ?? 0;
  }
}
