"""
Live metrics for the dashboard. Tracks per-utterance pipeline timings,
wake-word confidence, mic level, recent commands, and system stats.
"""

from __future__ import annotations

import asyncio
import math
import socket
import statistics
import time
from collections import deque
from pathlib import Path
from typing import Awaitable, Callable, Optional

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


Broadcaster = Callable[[dict], Awaitable[None]]


def _read_temp_c() -> Optional[float]:
    """Read CPU temp from /sys/class/thermal. Returns None if unavailable."""
    candidates = sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
    for p in candidates:
        try:
            t = p.read_text().strip()
            val = int(t) / 1000.0
            # Some zones are not CPU; pick first one with a sane reading.
            if 10 <= val <= 120:
                return val
        except Exception:
            continue
    return None


def _read_cpu_freq_ghz() -> Optional[float]:
    if _HAS_PSUTIL:
        try:
            f = psutil.cpu_freq()
            if f and f.current:
                return f.current / 1000.0
        except Exception:
            pass
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if "cpu MHz" in line:
                    return float(line.split(":")[1]) / 1000.0
    except Exception:
        return None
    return None


def _read_cpu_count() -> int:
    if _HAS_PSUTIL:
        try:
            return psutil.cpu_count(logical=False) or psutil.cpu_count() or 4
        except Exception:
            pass
    try:
        return len([1 for line in open("/proc/cpuinfo") if line.startswith("processor")])
    except Exception:
        return 4


class _CpuPercent:
    """Fallback CPU% reader using /proc/stat (no psutil)."""

    def __init__(self):
        self._prev = self._read()

    def _read(self):
        with open("/proc/stat") as f:
            line = f.readline()
        parts = [int(x) for x in line.split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        total = sum(parts)
        return idle, total

    def sample(self) -> float:
        idle, total = self._read()
        idle_d = idle - self._prev[0]
        total_d = total - self._prev[1]
        self._prev = (idle, total)
        if total_d <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (1.0 - idle_d / total_d)))


class MetricsTracker:
    """
    Owns pipeline timing state, recent-command log, and pushes WS messages.
    Pipeline calls the on_* hooks; main wires up broadcast + system poller.
    """

    def __init__(self, broadcaster: Broadcaster, hostname: Optional[str] = None):
        self._broadcast = broadcaster
        self.hostname = hostname or socket.gethostname()

        # Per-utterance state
        self._t_wake = 0.0
        self._t_listen_start = 0.0
        self._t_stt_start = 0.0
        self._t_stt_end = 0.0
        self._t_agent_start = 0.0
        self._t_intent_first = 0.0
        self._t_tts_first = 0.0
        self._current_text: Optional[str] = None

        # Snapshot fields
        self.last_wake_score = 0.0
        self.last_wake_ts = 0.0
        self.wake_active = False
        self.last_mic_db = -60.0
        self.last_stt_ms = 0
        self.last_intent_ms = 0
        self.last_tts_ms = 0
        self.last_e2e_ms = 0
        self.stt_history = deque(maxlen=20)  # for baseline delta

        # System
        self.cpu_pct = 0.0
        self.cpu_cores = _read_cpu_count()
        self.cpu_freq_ghz = _read_cpu_freq_ghz() or 0.0
        self.temp_c: Optional[float] = _read_temp_c()
        self._cpu_fallback = None if _HAS_PSUTIL else _CpuPercent()

        # Recent commands (newest first)
        self.recent_commands: deque[dict] = deque(maxlen=10)

        # Mic level ring buffer for waveform (~5s @ 50Hz)
        self.mic_levels: deque[float] = deque(maxlen=80)

        # Async coordination
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._mic_dirty = False
        self._mic_throttle_task: Optional[asyncio.Task] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    # ---- Sync hooks (callable from sounddevice / sync threads) ----

    def push_mic_rms(self, rms: float):
        """Called from audio callback (sync). Updates mic level ring."""
        if rms <= 0:
            db = -90.0
        else:
            db = 20.0 * math.log10(rms + 1e-9)
        # Clamp roughly into a usable range for the bars
        db = max(-70.0, min(0.0, db))
        self.last_mic_db = db
        # Normalize to 0..1 for waveform bars
        norm = (db + 70.0) / 70.0
        self.mic_levels.append(norm)
        # Schedule a throttled broadcast on the loop
        if self._loop and not self._mic_dirty:
            self._mic_dirty = True
            try:
                self._loop.call_soon_threadsafe(self._maybe_start_mic_throttle)
            except RuntimeError:
                pass

    def _maybe_start_mic_throttle(self):
        if self._mic_throttle_task is None or self._mic_throttle_task.done():
            self._mic_throttle_task = asyncio.create_task(self._mic_throttle_flush())

    async def _mic_throttle_flush(self):
        # ~10Hz mic broadcast
        await asyncio.sleep(0.1)
        self._mic_dirty = False
        await self._broadcast({
            "type": "mic",
            "db": round(self.last_mic_db, 1),
            "levels": list(self.mic_levels)[-50:],
        })

    # ---- Pipeline event hooks ----

    async def on_wake(self, score: float):
        self.last_wake_score = float(score)
        self.last_wake_ts = time.monotonic()
        self.wake_active = True
        self._t_wake = self.last_wake_ts
        await self._broadcast({
            "type": "wake",
            "score": round(self.last_wake_score, 3),
        })

    async def on_listen_start(self):
        self._t_listen_start = time.monotonic()

    async def on_transcript_done(self, text: str, t_stt_start: float):
        self._t_stt_start = t_stt_start
        self._t_stt_end = time.monotonic()
        self._current_text = text
        self.last_stt_ms = int((self._t_stt_end - self._t_stt_start) * 1000)
        if self.last_stt_ms > 0:
            self.stt_history.append(self.last_stt_ms)
        await self._push_metrics()

    async def on_agent_start(self):
        self._t_agent_start = time.monotonic()

    async def on_intent_first_token(self):
        self._t_intent_first = time.monotonic()
        if self._t_agent_start:
            self.last_intent_ms = int((self._t_intent_first - self._t_agent_start) * 1000)
        await self._push_metrics()

    async def on_tts_first_audio(self):
        self._t_tts_first = time.monotonic()
        if self._t_intent_first:
            self.last_tts_ms = int((self._t_tts_first - self._t_intent_first) * 1000)
        await self._push_metrics()

    async def on_utterance_complete(self):
        self.wake_active = False
        if self._current_text and self._t_wake:
            duration_ms = int((time.monotonic() - self._t_wake) * 1000)
            self.last_e2e_ms = duration_ms
            self.recent_commands.appendleft({
                "text": self._current_text,
                "ts": time.time(),
                "duration_ms": duration_ms,
            })
        # Reset per-utterance fields (keep the snapshot values)
        self._current_text = None
        await self._push_metrics()

    # ---- Snapshot construction ----

    def stt_baseline_delta_pct(self) -> Optional[int]:
        if len(self.stt_history) < 4 or self.last_stt_ms <= 0:
            return None
        baseline = statistics.median(self.stt_history)
        if baseline <= 0:
            return None
        return int(round((self.last_stt_ms - baseline) / baseline * 100))

    def thermal_label(self) -> str:
        if self.temp_c is None:
            return ""
        if self.temp_c >= 80:
            return "throttling"
        if self.temp_c >= 70:
            return "warm"
        return "passive cooled"

    def snapshot(self) -> dict:
        return {
            "type": "metrics",
            "host": self.hostname,
            "wake": {
                "score": round(self.last_wake_score, 3),
                "active": self.wake_active,
                "ts": self.last_wake_ts,
            },
            "stt_ms": self.last_stt_ms,
            "stt_delta_pct": self.stt_baseline_delta_pct(),
            "intent_ms": self.last_intent_ms,
            "tts_ms": self.last_tts_ms,
            "e2e_ms": self.last_e2e_ms,
            "wake_ms": 120,  # openwakeword frame budget; near-constant
            "system": {
                "cpu_pct": round(self.cpu_pct, 1),
                "cores": self.cpu_cores,
                "freq_ghz": round(self.cpu_freq_ghz, 2),
                "temp_c": round(self.temp_c, 1) if self.temp_c is not None else None,
                "thermal": self.thermal_label(),
            },
            "recent": list(self.recent_commands),
        }

    async def _push_metrics(self):
        await self._broadcast(self.snapshot())

    # ---- System stats poller ----

    async def system_stats_loop(self, interval: float = 2.0):
        # Prime psutil's first reading
        if _HAS_PSUTIL:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass
        while True:
            try:
                if _HAS_PSUTIL:
                    self.cpu_pct = float(psutil.cpu_percent(interval=None))
                elif self._cpu_fallback:
                    self.cpu_pct = self._cpu_fallback.sample()
                self.cpu_freq_ghz = _read_cpu_freq_ghz() or self.cpu_freq_ghz
                self.temp_c = _read_temp_c()
                await self._push_metrics()
            except Exception as e:
                print(f"[metrics] system stats error: {e}")
            await asyncio.sleep(interval)

