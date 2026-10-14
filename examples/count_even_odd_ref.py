import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    a = data[1:1 + n]
    even = sum(1 for x in a if x % 2 == 0)
    sys.stdout.write(f"Even = {even}, Odd = {n - even}\n")


main()
