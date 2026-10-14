import math
import sys

N = 10 ** 6


def build():
    bs = bytearray(b"\x01") * (N + 1)
    bs[:2] = b"\x00\x00"
    for i in range(2, math.isqrt(N) + 1):
        if bs[i]:
            bs[i * i:N + 1:i] = b"\x00" * ((N - i * i) // i + 1)
    pref = [0] * (N + 1)
    c = 0
    for i in range(N + 1):
        if bs[i]:
            c += 1
        pref[i] = c
    return pref


_PREF = build()


def main() -> None:
    data = sys.stdin.read().split()
    l, r = int(data[0]), int(data[1])
    if l > r:
        l, r = r, l
    print(_PREF[r] - (_PREF[l - 1] if l > 0 else 0))


main()
