"""Serial-port helpers. Ports are remembered by USB serial number too, so a COM number that
changes after re-plugging (common on Windows) is resolved automatically."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def list_ports():
    from serial.tools import list_ports as lp

    return list(lp.comports())


def resolve_port(port: str | None, serial_number: str | None) -> str | None:
    if not serial_number:
        return port
    try:
        for p in list_ports():
            if p.serial_number == serial_number:
                if p.device != port:
                    log.warning("port moved: %s -> %s (serial %s)", port, p.device, serial_number)
                return p.device
    except Exception:  # noqa: BLE001
        log.exception("port scan failed")
    return port
