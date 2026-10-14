import sys
from heapq import heappop, heappush


def main() -> None:
    data = sys.stdin.buffer.read().split()
    if not data:
        return
    q = int(data[0])
    heap: list[int] = []
    add = 0
    out: list[str] = []
    i = 1
    for _ in range(q):
        cmd = data[i].decode()
        i += 1
        if cmd == "P":
            x = int(data[i])
            i += 1
            heappush(heap, x - add)
        elif cmd == "A":
            v = int(data[i])
            i += 1
            add += v
        else:  # S
            if not heap:
                out.append("OH NO ICY PLS HELPPP")
            else:
                out.append(str(heappop(heap) + add))
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


main()
