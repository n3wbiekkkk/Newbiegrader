import math
import sys


def main() -> None:
    a, b = map(int, sys.stdin.read().split())
    g = math.gcd(a, b)
    lcm = a // g * b
    sys.stdout.write(f"{g} {lcm - a} {lcm - b}\n")


main()
