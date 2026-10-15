import bisect
import sys


def main() -> None:
    data = sys.stdin.buffer.read().split()
    if not data:
        return
    n, q = int(data[0]), int(data[1])
    a = list(map(int, data[2:2 + n]))
    qs = list(map(int, data[2 + n:2 + n + q]))
    out = []
    for x in qs:
        i = bisect.bisect_left(a, x)
        out.append(str(i + 1) if i < n else "-1")
    sys.stdout.write("\n".join(out) + "\n")


main()
