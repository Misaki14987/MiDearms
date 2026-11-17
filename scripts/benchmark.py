"""Offline deterministic workload; timing is informational, no network."""
import time
from midearms import dream
messages = [f'Prefer explicit configuration for module {i % 100}.' for i in range(10000)]
start = time.perf_counter()
notes = dream(messages)
assert len(notes) == 100
print(f'10000 messages -> {len(notes)} notes; {time.perf_counter()-start:.4f}s')
