import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    segs = [(data[i], data[i + 1]) for i in range(1, 2 * n, 2)]
    segs.sort(key=lambda s: (s[1], s[0]))
    cnt, last_end = 0, -1
    for s, e in segs:
        if s >= last_end:
            cnt += 1
            last_end = e
    sys.stdout.write(str(cnt) + "\n")


main()
