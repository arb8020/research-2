"""observe — wide event logging via stdlib logging.

All telemetry flows through Python's logging module. Every JSONL line carries an
explicit `kind` (see DESIGN.md):

- "log"    — a plain log line; the formatter stamps the kind
- "span"   — one wide event per unit of work, emitted once at completion
- "metric" — one gauge data point
- "artifact" — one named, typed structure a renderer draws

Console formatter shows human-readable output. JSONL formatter writes one
structured line per event with all attributes flattened to top level.
"""

from observe._artifact import artifact
from observe._log import setup_logging
from observe._metric import metric, metrics
from observe._span import span

__all__ = ["setup_logging", "span", "metric", "metrics", "artifact"]
