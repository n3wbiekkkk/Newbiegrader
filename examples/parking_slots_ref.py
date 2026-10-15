import heapq
import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    if len(data) < 3:
        return
    n, m, q = data[0], data[1], data[2]
    a = data[3:3 + n]
    cmds = data[3 + n:]
    heaps: dict = {}
    for i, t in enumerate(a, 1):
        heaps.setdefault(t, []).append(i)
    for h in heaps.values():
        heapq.heapify(h)
    occupied = bytearray(n + 1)
    out = []
    k = 0
    for _ in range(q):
        typ, v = cmds[k], cmds[k + 1]
        k += 2
        if typ == 0:
            h = heaps[v]
            while occupied[h[0]]:
                heapq.heappop(h)
            slot = heapq.heappop(h)
            occupied[slot] = 1
            out.append(str(slot))
        else:
            occupied[v] = 0
            heapq.heappush(heaps[a[v - 1]], v)
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


main()
