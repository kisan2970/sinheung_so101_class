"""Non-blocking single-key reader for console tools (Windows msvcrt / POSIX termios)."""

from __future__ import annotations

import os
import sys

# 한/영 키가 한글 상태여도 동작하도록 두벌식 자모 -> 영문 키 변환
_KO = dict(zip("ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔㅁㄴㅇㄹㅎㅗㅓㅏㅣㅋㅌㅊㅍㅠㅜㅡㅃㅉㄸㄲㅆㅒㅖ",
               "qwertyuiopasdfghjklzxcvbnmQWERTOP"))


def normalize_key(ch: str | None) -> str | None:
    if ch is None:
        return None
    ch = _KO.get(ch, ch)
    return ch.lower() if len(ch) == 1 and ch.isalpha() and ch.isascii() else ch

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
                return normalize_key(ch)
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
                return normalize_key(sys.stdin.read(1))
            return None
