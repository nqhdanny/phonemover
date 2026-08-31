"""Device detection via pymobiledevice3 (async usbmux API).

Note: pymobiledevice3 >= 2.x exposes an asyncio API. On Linux, the usbmuxd
service must be running (socket at /var/run/usbmuxd). On Windows the transport
differs but this wrapper stays the same.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class IDevice:
    """A connected iOS device."""

    udid: str
    connection: str  # "usb" | "network"


async def _list_async() -> list[IDevice]:
    from pymobiledevice3.usbmux import list_devices

    devices = await list_devices()
    result: list[IDevice] = []
    for d in devices:
        # Attribute names may shift between library versions — use getattr defensively.
        udid = getattr(d, "serial", None) or getattr(d, "udid", "") or ""
        conn = str(getattr(d, "connection_type", "") or "").lower()
        result.append(IDevice(udid=udid, connection="usb" if conn == "usb" else "network"))
    return result


def list_iphones() -> list[IDevice]:
    """Return connected iPhones (empty list when none / usbmuxd not running)."""
    try:
        return asyncio.run(_list_async())
    except FileNotFoundError:
        # usbmuxd service not present — treat as "no devices"
        return []
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Failed to enumerate iPhones: {exc}") from exc


if __name__ == "__main__":
    devices = list_iphones()
    print(f"Found {len(devices)} device(s)")
    for dev in devices:
        print(f"  - {dev.udid} ({dev.connection})")
