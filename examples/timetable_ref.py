import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    if not data:
        return
    t = data[0]
    idx = 1
    out = []
    for _ in range(t):
        n = data[idx]
        idx += 1
        events = []
        for _ in range(n):
            s, e = data[idx], data[idx + 1]
            idx += 2
            events.append((s, 1))
            events.append((e, -1))
        # half-open [s, e): an ending match frees the field before a
        # starting one at the same time.
        events.sort(key=lambda ev: (ev[0], ev[1]))
        cur = best = 0
        for _, d in events:
            cur += d
            if cur > best:
                best = cur
        out.append(str(best))
    sys.stdout.write("\n".join(out) + "\n")


main()
