"""Locate saved hook narration in a documentary using two audio matches.

Requires ffmpeg and numpy. No external services or speech-generation credits.
Ambiguous matches raise an error instead of choosing a guessed start time.
"""
from pathlib import Path
import subprocess

RATE = 4000


def audio(path, seconds):
    import numpy as np
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path), "-t", str(seconds),
        "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "pipe:1",
    ], check=True, capture_output=True)
    wave = np.frombuffer(result.stdout, dtype="<f4").astype("float64")
    if len(wave) < RATE or not np.isfinite(wave).all():
        raise RuntimeError(f"Invalid/short audio: {Path(path).name}")
    return wave


def match(signal, template):
    import numpy as np
    size = len(template)
    if len(signal) < size:
        raise RuntimeError("Documentary scan is shorter than hook sample")
    template = template - template.mean()
    energy = float(np.dot(template, template))
    if energy < 1e-10:
        raise RuntimeError("Hook sample is silent")
    length = 1 << (len(signal) + size - 2).bit_length()
    convolution = np.fft.irfft(
        np.fft.rfft(signal, length) * np.fft.rfft(template[::-1], length), length)
    numerator = convolution[size - 1:len(signal)]
    sums = np.concatenate(([0.0], np.cumsum(signal)))
    squares = np.concatenate(([0.0], np.cumsum(signal * signal)))
    window_sum = sums[size:] - sums[:-size]
    window_energy = squares[size:] - squares[:-size] - window_sum * window_sum / size
    denominator = np.sqrt(np.maximum(window_energy, 0) * energy)
    scores = np.divide(numerator, denominator, out=np.zeros_like(numerator),
                       where=denominator > 1e-10)
    scores = np.clip(scores, -1, 1)
    peak = int(np.argmax(scores))
    confidence = float(scores[peak])
    competing = scores.copy()
    gap = int(0.75 * RATE)
    competing[max(0, peak - gap):min(len(competing), peak + gap + 1)] = -1
    alternative = float(competing.max())
    if confidence < 0.60:
        raise RuntimeError(f"Audio match too weak ({confidence:.3f})")
    if alternative > confidence * 0.90:
        raise RuntimeError(f"Audio match ambiguous ({confidence:.3f} vs {alternative:.3f})")
    return peak, confidence, alternative


def locate_arrays(documentary, hook):
    import numpy as np
    frame = RATE // 20
    frames = len(hook) // frame
    rms = np.sqrt(np.mean(hook[:frames * frame].reshape(frames, frame) ** 2, axis=1))
    active = np.flatnonzero(rms > max(float(rms.max()) * 0.10, 1e-5))
    if not len(active):
        raise RuntimeError("Hook is silent")
    begin = int(active[0] * frame)
    end = min(len(hook), int((active[-1] + 1) * frame))
    span = end - begin
    if span < 6 * RATE:
        raise RuntimeError("Hook is too short for two independent samples")
    width = min(4 * RATE, span // 3)
    offsets = (begin + int(0.2 * RATE), end - width - int(0.2 * RATE))
    matches = []
    for offset in offsets:
        location, confidence, alternative = match(documentary, hook[offset:offset + width])
        matches.append({
            "start_seconds": (location - offset) / RATE,
            "confidence": round(confidence, 4), "alternative": round(alternative, 4),
        })
    starts = [m["start_seconds"] for m in matches]
    if min(starts) < 0 or abs(starts[0] - starts[1]) > 0.15:
        raise RuntimeError(f"Hook samples disagree about timing: {starts}")
    return {
        "start_seconds": round(sum(starts) / len(starts), 3),
        "method": "two_independent_normalized_audio_matches",
        "matches": matches,
    }


def find_hook(documentary, hook, scan_seconds=180):
    try:
        import numpy
    except ImportError:
        raise RuntimeError("Install audio matching: python -m pip install numpy")
    return locate_arrays(audio(documentary, scan_seconds), audio(hook, 120))
