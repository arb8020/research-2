"""Standard LogRecord attributes — used to distinguish extra= kwargs from stdlib internals."""

import logging

# Every attribute that stdlib puts on a LogRecord by default.
# Anything else on the record is an extra= kwarg (our structured fields).
STANDARD_RECORD_ATTRS: frozenset[str] = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys() | {"message", "asctime"}
)

# `name` on a LogRecord is the logger name — stdlib raises if extra= tries to set
# it. Metric points carry their name under this key and the JSONL formatter
# renames it to "name" on the way to disk.
METRIC_NAME_ATTR = "metric_name"
