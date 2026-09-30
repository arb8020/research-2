# Damaging-secondary rotation closure

Six moves already used the generic generated one-effect secondary pipeline but
lacked per-descriptor differential evidence: Sacred Fire, Blaze Kick, Poison
Tail, Luster Purge, Mist Ball, and Muddy Water. The fixture generator now
includes legal holders (falling back to legal Smeargle + Sketch where needed)
and frozen seeds that make each secondary apply.

The exact cases prove hit staging, critical/damage draws, the secondary draw,
status or single-stat application, canonical state, and subsequent residual
behavior where applicable. No kernel or generated effect representation was
changed. Blaze Kick and Poison Tail were already classified through their
high-critical-ratio family; the new cases close their secondary evidence while
the other four move descriptors advance from unsupported to implemented.
