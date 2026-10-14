import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    pts = [(data[i], data[i + 1]) for i in range(1, 2 * n, 2)]
    pts.sort(key=lambda p: (p[0] * p[0] + p[1] * p[1], p[0], p[1]))
    sys.stdout.write("\n".join(f"{x} {y}" for x, y in pts) + "\n")


main()
