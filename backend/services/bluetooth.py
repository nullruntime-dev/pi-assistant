import asyncio
import re
from typing import Optional


_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", re.IGNORECASE)
_DEVICE_LINE = re.compile(r"^Device\s+([0-9A-F:]{17})\s+(.*)$", re.IGNORECASE)
# wpctl status lines look like:  " │      *   35. bluez_output.AA_BB_CC_DD_EE_FF.a2dp-sink  [vol: 0.40]"
_SINK_LINE = re.compile(r"(\d+)\.\s+(bluez_output\.\S+)")


class BluetoothError(Exception):
    pass


def _mac_to_under(mac: str) -> str:
    return mac.replace(":", "_").upper()


async def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    """Run a command, return (rc, stdout, stderr). Never raises on non-zero."""
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
        raise BluetoothError(f"{cmd[0]} timed out")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _bctl(*args: str, timeout: float = 10.0) -> str:
    """Run `bluetoothctl <args...>` and return stdout. Raises on failure."""
    rc, out, err = await _run(["bluetoothctl", *args], timeout=timeout)
    if rc != 0:
        raise BluetoothError(f"bluetoothctl {' '.join(args)} failed: {err.strip() or out.strip()}")
    return out


def _parse_device_list(text: str) -> list[tuple[str, str]]:
    devices = []
    for line in text.splitlines():
        m = _DEVICE_LINE.match(line.strip())
        if m:
            devices.append((m.group(1).upper(), m.group(2).strip()))
    return devices


def _parse_info(text: str) -> dict:
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("Device "):
            k, _, v = line.partition(":")
            info[k.strip().lower()] = v.strip()
    return info


class BluetoothService:
    """Manage Bluetooth pairing and audio routing on a PipeWire/BlueZ system."""

    def __init__(self):
        self._scan_task: Optional[asyncio.Task] = None

    async def list_devices(self) -> list[dict]:
        """Return known devices with their paired/connected/trusted state."""
        paired_text = await _bctl("devices", "Paired")
        all_text = await _bctl("devices")
        paired = {mac for mac, _ in _parse_device_list(paired_text)}

        results: list[dict] = []
        seen: set[str] = set()
        for mac, name in _parse_device_list(all_text):
            if mac in seen:
                continue
            seen.add(mac)
            info: dict = {}
            try:
                info_text = await _bctl("info", mac, timeout=5.0)
                info = _parse_info(info_text)
            except BluetoothError:
                pass
            results.append({
                "mac": mac,
                "name": info.get("name") or name or mac,
                "paired": mac in paired or info.get("paired", "").lower() == "yes",
                "connected": info.get("connected", "").lower() == "yes",
                "trusted": info.get("trusted", "").lower() == "yes",
                "icon": info.get("icon", ""),
            })
        # Paired/connected first, then others
        results.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
        return results

    async def scan(self, duration: float = 8.0) -> None:
        """Run a discovery scan for `duration` seconds, then stop."""
        if self._scan_task and not self._scan_task.done():
            return  # already scanning
        self._scan_task = asyncio.create_task(self._scan(duration))

    async def _scan(self, duration: float) -> None:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", "--timeout", str(int(duration)), "scan", "on",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=duration + 5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    def is_scanning(self) -> bool:
        return bool(self._scan_task and not self._scan_task.done())

    async def connect(self, mac: str) -> dict:
        """Pair (if needed), trust, connect, and route audio to the device."""
        if not _MAC_RE.match(mac):
            raise BluetoothError(f"invalid MAC: {mac}")

        # Check state up front so we only pair if we have to — pair on an already-paired
        # device just errors out.
        try:
            info = _parse_info(await _bctl("info", mac, timeout=5.0))
        except BluetoothError:
            info = {}

        if info.get("paired", "").lower() != "yes":
            await _bctl("pair", mac, timeout=30.0)

        if info.get("trusted", "").lower() != "yes":
            try:
                await _bctl("trust", mac, timeout=5.0)
            except BluetoothError:
                pass  # non-fatal; device will still work this session

        if info.get("connected", "").lower() != "yes":
            await _bctl("connect", mac, timeout=20.0)

        # Give PipeWire a moment to register the new bluez sink.
        sink_id = await self._wait_for_sink(mac, timeout=5.0)
        default_set = False
        if sink_id is not None:
            default_set = await self._set_default_sink(sink_id)

        return {"mac": mac, "connected": True, "sink_id": sink_id, "default_set": default_set}

    async def disconnect(self, mac: str) -> None:
        if not _MAC_RE.match(mac):
            raise BluetoothError(f"invalid MAC: {mac}")
        await _bctl("disconnect", mac, timeout=10.0)

    async def _wait_for_sink(self, mac: str, timeout: float) -> Optional[int]:
        deadline = asyncio.get_event_loop().time() + timeout
        target = _mac_to_under(mac)
        while asyncio.get_event_loop().time() < deadline:
            sink_id = await self._find_sink(target)
            if sink_id is not None:
                return sink_id
            await asyncio.sleep(0.3)
        return None

    async def _find_sink(self, mac_under: str) -> Optional[int]:
        rc, out, _ = await _run(["wpctl", "status"], timeout=5.0)
        if rc != 0:
            return None
        for line in out.splitlines():
            m = _SINK_LINE.search(line)
            if m and mac_under in m.group(2).upper():
                return int(m.group(1))
        return None

    async def _set_default_sink(self, sink_id: int) -> bool:
        rc, _, _ = await _run(["wpctl", "set-default", str(sink_id)], timeout=5.0)
        return rc == 0


bluetooth_service = BluetoothService()
