import math
import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    p, q = 0, 1
    for i in range(n):
        a, b = data[1 + 2 * i], data[2 + 2 * i]
        p, q = p * b + a * q, q * b
        g = math.gcd(abs(p), abs(q))
        p, q = p // g, q // g
    if q < 0:
        p, q = -p, -q
    sys.stdout.write(f"{p}/{q}\n")


main()
