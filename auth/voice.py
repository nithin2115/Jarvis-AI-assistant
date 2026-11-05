"""
JARVIS Auth — Voice Verification
Pure numpy/scipy MFCC extraction + cosine-similarity speaker matching.
No heavy dependencies — scipy only.
Audio arrives as base64-encoded raw float32 PCM from the browser Web Audio API.
"""
import base64, logging
from typing import Optional, Tuple
import numpy as np

logger = logging.getLogger("jarvis.voice")

SR       = 16000   # sample rate expected from browser
N_MFCC   = 13
N_MELS   = 26
N_FFT    = 512
FRAME_MS = 25      # frame length in ms
HOP_MS   = 10      # hop in ms


# ── Audio decode ───────────────────────────────────────────────

def decode_pcm(b64: str) -> Optional[np.ndarray]:
    """Decode base64 float32 PCM (sent from browser ScriptProcessorNode)."""
    try:
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
        return np.frombuffer(raw, dtype=np.float32).copy()
    except Exception as e:
        logger.error(f"[VOICE] decode error: {e}")
        return None


# ── MFCC (pure numpy) ──────────────────────────────────────────

def _mel_filterbank(sr, n_fft, n_mels, low_hz=80, high_hz=None):
    high_hz  = high_hz or sr // 2
    low_mel  = 2595 * np.log10(1 + low_hz  / 700)
    high_mel = 2595 * np.log10(1 + high_hz / 700)
    mels     = np.linspace(low_mel, high_mel, n_mels + 2)
    hz       = 700 * (10 ** (mels / 2595) - 1)
    bins     = np.floor((n_fft + 1) * hz / sr).astype(int)
    fb       = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        lo, mid, hi = bins[m-1], bins[m], bins[m+1]
        if mid > lo:
            fb[m-1, lo:mid] = (np.arange(lo, mid) - lo) / (mid - lo)
        if hi > mid:
            fb[m-1, mid:hi] = (hi - np.arange(mid, hi))  / (hi - mid)
    return fb


_FB = _mel_filterbank(SR, N_FFT, N_MELS)   # pre-computed


def _dct(x):
    """Type-II DCT, ortho-normalised, along last axis."""
    N  = x.shape[-1]
    k  = np.arange(N)
    v  = np.cos(np.pi * np.outer(np.arange(N), (k + 0.5) / N))
    y  = x @ v.T
    y  = y / np.sqrt(2 * N)
    y[..., 0] /= np.sqrt(2)
    return y


def extract_features(samples: np.ndarray) -> Optional[np.ndarray]:
    """
    Extract a 2*N_MFCC feature vector (mean + std of MFCCs).
    Returns None if the sample is too short or silent.
    """
    if samples is None or len(samples) < SR // 4:
        return None

    # Normalise
    peak = np.max(np.abs(samples))
    if peak < 1e-6:
        return None
    samples = samples / peak

    # Pre-emphasis
    samples = np.append(samples[0], samples[1:] - 0.97 * samples[:-1])

    # Frame + window
    frame_len = int(SR * FRAME_MS / 1000)
    hop_len   = int(SR * HOP_MS  / 1000)
    n_frames  = max(1, (len(samples) - frame_len) // hop_len + 1)
    idx       = (np.arange(frame_len)[None, :] +
                 np.arange(n_frames)[:, None] * hop_len)
    idx       = np.clip(idx, 0, len(samples) - 1)
    frames    = samples[idx] * np.hamming(frame_len)

    # Power spectrum
    mag   = np.abs(np.fft.rfft(frames, n=N_FFT))
    power = (mag ** 2) / N_FFT

    # Mel filterbank + log
    fb  = power @ _FB.T
    fb  = np.where(fb < 1e-10, 1e-10, fb)
    log = 20 * np.log10(fb)

    # DCT → MFCCs
    mfcc = _dct(log)[:, :N_MFCC]

    return np.concatenate([np.mean(mfcc, axis=0),
                           np.std(mfcc,  axis=0)]).astype(np.float32)


def compare(stored: np.ndarray, candidate: np.ndarray,
            threshold: float = 0.82) -> Tuple[bool, float]:
    """
    Cosine similarity between two feature vectors.
    Returns (match: bool, similarity: float  0-1).
    """
    if stored is None or candidate is None:
        return False, 0.0
    a   = stored    / (np.linalg.norm(stored)    + 1e-10)
    b   = candidate / (np.linalg.norm(candidate) + 1e-10)
    sim = float(np.dot(a, b))
    return sim >= threshold, max(0.0, sim)


def extract_from_b64(b64: str) -> Optional[np.ndarray]:
    """Convenience: decode PCM → extract features."""
    return extract_features(decode_pcm(b64))
