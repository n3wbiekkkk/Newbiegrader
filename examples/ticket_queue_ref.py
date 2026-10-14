import sys
from collections import deque


def main() -> None:
    data = sys.stdin.buffer.read().split()
    q = int(data[0])
    dq: deque = deque()
    out = []
    i = 1
    for _ in range(q):
        if data[i] == b"1":
            dq.append(data[i + 1].decode())
            i += 2
        else:
            i += 1
            out.append(dq.popleft() if dq else "-1")
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


main()
