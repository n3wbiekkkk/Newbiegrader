import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    pairs = [(data[i], data[i + 1]) for i in range(1, 2 * n, 2)]
    pairs.sort(key=lambda p: (-p[1], p[0]))
    sys.stdout.write(" ".join(str(pid) for pid, _ in pairs) + "\n")


main()
