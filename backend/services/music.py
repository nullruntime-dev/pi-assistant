import asyncio
import subprocess
from typing import Optional

from youtubesearchpython import VideosSearch


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
        search = VideosSearch(query, limit=limit)
        results = await asyncio.to_thread(search.result)

        videos = []
        for item in results.get("result", []):
            videos.append({
                "title": item.get("title", "Unknown"),
                "url": item.get("link", ""),
                "duration": item.get("duration", ""),
                "channel": item.get("channel", {}).get("name", "Unknown"),
            })

        return videos

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

        # Play audio using yt-dlp + mpv (audio only)
        try:
            self._process = subprocess.Popen(
                [
                    "mpv",
                    "--no-video",
                    "--really-quiet",
                    "--no-terminal",
                    "--audio-device=auto",  # Auto-detect audio device
                    "--volume=80",
                    url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"Now playing: {title}"
        except FileNotFoundError:
            # Try ffplay as fallback
            try:
                # Get audio URL with yt-dlp
                result = subprocess.run(
                    ["yt-dlp", "-g", "-f", "bestaudio", url],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                audio_url = result.stdout.strip()

                if audio_url:
                    self._process = subprocess.Popen(
                        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return f"Now playing: {title}"
            except Exception as e:
                return f"Playback failed: {e}. Install mpv: sudo pacman -S mpv"

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
