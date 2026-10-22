"""Audio helpers for telephony audio (G.711 μ-law, 8 kHz mono). Pure Python, no native deps."""

from __future__ import annotations

import io
import math
import struct
import wave


def _ulaw_to_linear(u: int) -> int:
    u = ~u & 0xFF
    sign = u & 0x80
    exponent = (u >> 4) & 0x07
    mantissa = u & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


ULAW_TO_PCM16: tuple[int, ...] = tuple(_ulaw_to_linear(i) for i in range(256))


def _linear_to_ulaw(sample: int) -> int:
    bias, clip = 0x84, 32635
    sign = 0x80 if sample < 0 else 0
    sample = min(abs(sample), clip) + bias
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not sample & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def ulaw_to_pcm16(data: bytes) -> bytes:
    return struct.pack(f"<{len(data)}h", *(ULAW_TO_PCM16[b] for b in data))


def pcm16_to_ulaw(data: bytes) -> bytes:
    samples = struct.unpack(f"<{len(data) // 2}h", data[: len(data) // 2 * 2])
    return bytes(_linear_to_ulaw(s) for s in samples)


def resample_pcm16(data: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear-interpolation resampler (adequate for speech-band telephony audio)."""
    if src_rate == dst_rate or not data:
        return data
    samples = struct.unpack(f"<{len(data) // 2}h", data[: len(data) // 2 * 2])
    n_out = int(len(samples) * dst_rate / src_rate)
    ratio = src_rate / dst_rate
    out = []
    last = len(samples) - 1
    for i in range(n_out):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        a = samples[min(j, last)]
        b = samples[min(j + 1, last)]
        out.append(int(a + (b - a) * frac))
    return struct.pack(f"<{len(out)}h", *out)


def pcm16_to_wav(data: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(data)
    return buf.getvalue()


def mulaw_to_wav16k(data: bytes) -> bytes:
    """Telephony μ-law 8 kHz -> 16 kHz PCM WAV (for REST endpoints that want 16 kHz)."""
    return pcm16_to_wav(resample_pcm16(ulaw_to_pcm16(data), 8000, 16000), 16000)


def ulaw_rms(data: bytes) -> float:
    if not data:
        return 0.0
    return math.sqrt(sum(ULAW_TO_PCM16[b] ** 2 for b in data) / len(data))


def tone_ulaw(freq: float, ms: int, amplitude: int = 8000, rate: int = 8000) -> bytes:
    """Synthetic test audio."""
    n = rate * ms // 1000
    return bytes(_linear_to_ulaw(int(amplitude * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))


def silence_ulaw(ms: int, rate: int = 8000) -> bytes:
    return bytes([0xFF]) * (rate * ms // 1000)


class TelephonyFormatError(ValueError):
    pass


def validate_twilio_media_format(media_format: dict | None) -> None:
    """Twilio Media Streams always send audio/x-mulaw, 8000 Hz, mono. Refuse anything else."""
    fmt = media_format or {}
    if (
        str(fmt.get("encoding", "")).lower() != "audio/x-mulaw"
        or int(fmt.get("sampleRate", 0)) != 8000
        or int(fmt.get("channels", 1)) != 1
    ):
        raise TelephonyFormatError(f"Unsupported telephony audio format: {fmt!r}")


class EnergyVAD:
    """Small energy-based endpointer for providers without server-side turn detection.

    Feed 20 ms μ-law frames; returns "start" when speech begins and "end" after
    `silence_ms` of quiet following at least `min_speech_ms` of speech.
    """

    def __init__(self, threshold: float = 900.0, min_speech_ms: int = 200, silence_ms: int = 600, frame_ms: int = 20):
        self.threshold = threshold
        self.min_speech_frames = max(1, min_speech_ms // frame_ms)
        self.silence_frames = max(1, silence_ms // frame_ms)
        self.frame_bytes = 8 * frame_ms
        self.in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._pending = b""

    def feed(self, chunk: bytes) -> list[str]:
        events = []
        self._pending += chunk
        while len(self._pending) >= self.frame_bytes:
            frame, self._pending = self._pending[: self.frame_bytes], self._pending[self.frame_bytes :]
            loud = ulaw_rms(frame) >= self.threshold
            if not self.in_speech:
                self._speech_run = self._speech_run + 1 if loud else 0
                if self._speech_run >= self.min_speech_frames:
                    self.in_speech, self._silence_run = True, 0
                    events.append("start")
            else:
                self._silence_run = 0 if loud else self._silence_run + 1
                if self._silence_run >= self.silence_frames:
                    self.in_speech, self._speech_run = False, 0
                    events.append("end")
        return events
