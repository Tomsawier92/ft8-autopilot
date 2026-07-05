"""Jelfeldolgozás — burkoló, kulcsolás."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, sosfiltfilt


def bandpass_cw(x: np.ndarray, fs: float, lo: float = 300.0, hi: float = 2400.0) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size < 32:
        return x
    sos = butter(4, [lo, hi], btype="band", fs=fs, output="sos")
    return sosfiltfilt(sos, x)


def envelope(x: np.ndarray, fs: float) -> np.ndarray:
    x = bandpass_cw(x, fs)
    if x.size >= 16:
        from scipy.signal import hilbert

        env = np.abs(hilbert(x))
    else:
        env = np.abs(x)
    win = max(5, int(0.012 * fs))
    return uniform_filter1d(env, min(win, max(3, env.size // 4)), mode="nearest")


def envelope_and_key(x: np.ndarray, fs: float, prev_on: bool) -> tuple[np.ndarray, np.ndarray, bool]:
    env = envelope(x, fs)
    p_lo = float(np.percentile(env, 22))
    p_hi = float(np.percentile(env, 90))
    span = max(p_hi - p_lo, 1e-12)
    thr_on = p_lo + 0.48 * span
    thr_off = p_lo + 0.14 * span
    keyed = np.zeros(env.size, dtype=np.uint8)
    on = prev_on
    for i in range(env.size):
        v = env[i]
        if on:
            if v < thr_off:
                on = False
        elif v > thr_on:
            on = True
        keyed[i] = 1 if on else 0
    return env, keyed, on


def signal_strong_enough(x: np.ndarray, min_rms: float = 0.0008) -> bool:
    rms = float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))
    return rms >= min_rms
