"""Audio út teljesítmény — scipy vs fast decimate."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.ft8.audio_fast import downsample_48k_to_12k

N = 2000
x = np.random.randn(4800 * N).astype(np.float32)

t0 = time.perf_counter()
for i in range(N):
  downsample_48k_to_12k(x[i * 4800 : (i + 1) * 4800])
fast_s = time.perf_counter() - t0

t0 = time.perf_counter()
for i in range(N):
  resample_poly(x[i * 4800 : (i + 1) * 4800], 1, 4)
slow_s = time.perf_counter() - t0

print(f"fast: {fast_s:.3f}s  scipy: {slow_s:.3f}s  speedup: {slow_s/fast_s:.1f}x")
