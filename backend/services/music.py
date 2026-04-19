import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import yt_dlp


_NORMAL_VOLUME = 55   # default playback level; low enough that the mic beats it
_DUCKED_VOLUME = 10   # while the assistant is listening or speaking

OnChange = Callable[[Optional[dict]], Awaitable[None]]


def _ytdlp_path() -> str:
    """Locate a working yt-dlp — prefer the venv's over any outdated system one."""
    venv_bin = Path(sys.executable).parent / "yt-dlp"
    if venv_bin.exists():
        return str(venv_bin)
    return shutil.which("yt-dlp") or "yt-dlp"


def _format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return ""
    total = int(seconds)
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class MusicPlayer:
    """Search and play music from YouTube."""

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._ipc_path: Optional[str] = None
        self._ducked: bool = False
        self._current: Optional[dict] = None
        self._watcher: Optional[asyncio.Task] = None
        self.on_change: Optional[OnChange] = None

    @property
    def current_track(self) -> Optional[dict]:
        return self._current

    async def _emit_change(self):
        if self.on_change is None:
            return
        try:
            await self.on_change(self._current)
        except Exception as e:
            print(f"[music] on_change failed: {e}")

    async def _watch_until_exit(self):
        """Detect when mpv exits on its own (song finished) and clear state."""
        proc = self._process
        if proc is None:
            return
        try:
            await asyncio.to_thread(proc.wait)
        except Exception:
            return
        # Only clear if this is still the active process (not replaced by a new play()).
        if self._process is proc:
            self._process = None
            self._current = None
            self._ducked = False
            await self._emit_change()

    def _send_mpv(self, command: list) -> bool:
        """Send a JSON-IPC command to mpv. Returns True on success."""
        if not self._ipc_path or not os.path.exists(self._ipc_path):
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                s.connect(self._ipc_path)
                s.sendall((json.dumps({"command": command}) + "\n").encode())
            return True
        except Exception:
            return False

    async def _await_ipc(self, timeout: float = 2.0):
        """Yield until the IPC socket appears or timeout. Does not block the event loop."""
        if not self._ipc_path:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(self._ipc_path):
                return
            await asyncio.sleep(0.05)

    def duck(self):
        """Lower music volume while the assistant listens or speaks."""
        if self.is_playing() and not self._ducked:
            if self._send_mpv(["set_property", "volume", _DUCKED_VOLUME]):
                self._ducked = True

    def unduck(self):
        """Restore music to normal listening volume."""
        if self.is_playing() and self._ducked:
            if self._send_mpv(["set_property", "volume", _NORMAL_VOLUME]):
                self._ducked = False

    async def search(self, query: str, limit: int = 1) -> list[dict]:
        """
        Search YouTube for videos.

        Returns:
            List of {title, url, duration, channel}
        """
        def _search() -> list[dict]:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extract_flat": "in_playlist",
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            videos = []
            for e in (info or {}).get("entries", []) or []:
                thumbs = e.get("thumbnails") or []
                thumbnail = e.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None)
                videos.append({
                    "title": e.get("title", "Unknown"),
                    "url": e.get("url") or e.get("webpage_url", ""),
                    "duration": _format_duration(e.get("duration")),
                    "channel": e.get("channel") or e.get("uploader", "Unknown"),
                    "thumbnail": thumbnail,
                })
            return videos

        return await asyncio.to_thread(_search)

    async def play(self, query: str) -> str:
        """
        Search and play audio from YouTube.

        Returns:
            Status message
        """
        t0 = time.monotonic()

        # Stop any current playback
        await self._stop_internal(emit=False)

        # Search for video
        results = await self.search(query, limit=1)
        t_search = time.monotonic() - t0
        if not results:
            return f"No results found for '{query}'"

        video = results[0]
        url = video["url"]
        title = video["title"]

        print(f"[music] search took {t_search:.2f}s -> {title}")

        ytdlp = _ytdlp_path()

        # Play audio using yt-dlp + mpv (audio only)
        self._ipc_path = os.path.join(
            tempfile.gettempdir(), f"pi-assistant-mpv-{os.getpid()}.sock"
        )
        try:
            os.unlink(self._ipc_path)
        except FileNotFoundError:
            pass

        try:
            t1 = time.monotonic()
            self._process = subprocess.Popen(
                [
                    "mpv",
                    "--no-video",
                    "--no-terminal",
                    "--audio-device=auto",
                    f"--volume={_NORMAL_VOLUME}",
                    f"--input-ipc-server={self._ipc_path}",
                    f"--script-opts=ytdl_hook-ytdl_path={ytdlp}",
                    url,
                ],
                stdout=subprocess.DEVNULL,
            )
            self._ducked = False
            self._current = {
                "title": title,
                "channel": video.get("channel"),
                "duration": video.get("duration"),
                "thumbnail": video.get("thumbnail"),
            }
            # Fire-and-forget: don't block the response on the IPC socket appearing.
            # duck() will no-op until mpv is up, which is fine.
            asyncio.create_task(self._await_ipc(timeout=2.0))
            self._watcher = asyncio.create_task(self._watch_until_exit())
            await self._emit_change()
            print(f"[music] mpv spawn took {time.monotonic() - t1:.2f}s (total so far {time.monotonic() - t0:.2f}s)")
            return f"Now playing: {title}"
        except FileNotFoundError:
            # Try ffplay as fallback
            try:
                result = subprocess.run(
                    [ytdlp, "-g", "-f", "bestaudio", url],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                audio_url = result.stdout.strip()

                if audio_url:
                    self._process = subprocess.Popen(
                        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_url],
                        stdout=subprocess.DEVNULL,
                    )
                    return f"Now playing: {title}"
            except Exception as e:
                return f"Playback failed: {e}. Install mpv: sudo apt install mpv"

        return f"Found: {title}, but no player available. Install mpv."

    async def _stop_internal(self, emit: bool) -> str:
        """Stop playback and optionally notify subscribers."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            self._ducked = False
            self._current = None
            if self._watcher and not self._watcher.done():
                self._watcher.cancel()
            self._watcher = None
            if self._ipc_path:
                try:
                    os.unlink(self._ipc_path)
                except FileNotFoundError:
                    pass
                self._ipc_path = None
            if emit:
                await self._emit_change()
            return "Music stopped"
        return "Nothing playing"

    def stop(self) -> str:
        """Stop current playback (sync wrapper for callers without an event loop)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return asyncio.run(self._stop_internal(emit=True))
        # In an async context: schedule the stop+emit and return the message immediately.
        msg = "Music stopped" if self._process else "Nothing playing"
        loop.create_task(self._stop_internal(emit=True))
        return msg

    def is_playing(self) -> bool:
        """Check if music is currently playing."""
        if self._process:
            return self._process.poll() is None
        return False


# Global instance
music_player = MusicPlayer()
