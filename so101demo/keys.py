"""Non-blocking single-key reader for console tools (Windows msvcrt / POSIX termios)."""

from __future__ import annotations

import os
import sys

if os.name == "nt":
    import msvcrt

    class KeyReader:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self) -> str | None:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # arrow/function key prefix
                    msvcrt.getwch()
                    return None
                return ch
            return None
else:
    import select
    import termios
    import tty

    class KeyReader:
        def __enter__(self):
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            return self

        def __exit__(self, *a):
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

        def get(self) -> str | None:
            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1)
            return None
