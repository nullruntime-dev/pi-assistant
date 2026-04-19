import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yt_dlp


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
                videos.append({
                    "title": e.get("title", "Unknown"),
                    "url": e.get("url") or e.get("webpage_url", ""),
                    "duration": _format_duration(e.get("duration")),
                    "channel": e.get("channel") or e.get("uploader", "Unknown"),
                })
            return videos

        return await asyncio.to_thread(_search)

    async def play(self, query: str) -> str:
        """
        Search and play audio from YouTube.

        Returns:
            Status message
        """
        # Stop any current playback
        self.stop()

        # Search for video
        results = await self.search(query, limit=1)
        if not results:
            return f"No results found for '{query}'"

        video = results[0]
        url = video["url"]
        title = video["title"]

        print(f"Playing: {title}")

        ytdlp = _ytdlp_path()

        # Play audio using yt-dlp + mpv (audio only)
        try:
            self._process = subprocess.Popen(
                [
                    "mpv",
                    "--no-video",
                    "--no-terminal",
                    "--audio-device=auto",
                    "--volume=80",
                    f"--script-opts=ytdl_hook-ytdl_path={ytdlp}",
                    url,
                ],
                stdout=subprocess.DEVNULL,
            )
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

    def stop(self) -> str:
        """Stop current playback."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            return "Music stopped"
        return "Nothing playing"

    def is_playing(self) -> bool:
        """Check if music is currently playing."""
        if self._process:
            return self._process.poll() is None
        return False


# Global instance
music_player = MusicPlayer()
