import sys


def main() -> None:
    n = int(sys.stdin.read().strip())
    a, b, total = 0, 1, 0
    for _ in range(n + 1):
        total += a
        a, b = b, a + b
    sys.stdout.write(str(total) + "\n")


main()
