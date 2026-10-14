import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    a = data[1:1 + n]
    sys.stdout.write(f"{min(a)}\n{sum(a)}\n")


main()
