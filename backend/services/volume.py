import asyncio
import re


_VOLUME_RE = re.compile(r"Volume:\s*([0-9.]+)(?:\s*\[(MUTED)\])?")
_DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"


class VolumeError(Exception):
    pass


async def _run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise VolumeError(f"{cmd[0]} timed out")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class VolumeService:
    """System volume control via PipeWire's wpctl on the default sink."""

    async def get(self) -> dict:
        rc, out, err = await _run(["wpctl", "get-volume", _DEFAULT_SINK])
        if rc != 0:
            raise VolumeError(err.strip() or out.strip() or "wpctl get-volume failed")
        m = _VOLUME_RE.search(out)
        if not m:
            raise VolumeError(f"could not parse wpctl output: {out!r}")
        return {"level": float(m.group(1)), "muted": m.group(2) == "MUTED"}

    async def set(self, level: float) -> dict:
        if not 0.0 <= level <= 1.5:
            raise VolumeError(f"level out of range: {level}")
        # wpctl accepts the bare float (e.g. "0.40"). Cap at 1.0 to avoid distortion;
        # callers that explicitly want boost can pass up to 1.5.
        rc, out, err = await _run(["wpctl", "set-volume", _DEFAULT_SINK, f"{level:.2f}"])
        if rc != 0:
            raise VolumeError(err.strip() or out.strip() or "wpctl set-volume failed")
        return await self.get()


volume_service = VolumeService()
