import sys


def main() -> None:
    data = sys.stdin.buffer.read().split()
    if not data:
        return
    it = iter(data)
    n = int(next(it))
    q = int(next(it))
    diff = [0] * (n + 1)
    for _ in range(q):
        l = int(next(it)) - 1
        r = int(next(it)) - 1
        v = int(next(it))
        diff[l] += v
        if r + 1 < n:
            diff[r + 1] -= v
    out = []
    cur = 0
    for d in diff[:n]:
        cur += d
        out.append(str(cur))
    sys.stdout.write(' '.join(out))


main()
