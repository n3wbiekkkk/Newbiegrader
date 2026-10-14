import sys
from itertools import accumulate


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n, q = data[0], data[1]
    a = data[2:2 + n]
    pref = [0] + list(accumulate(a))
    queries = data[2 + n:]
    out = []
    for i in range(q):
        l, r = queries[2 * i], queries[2 * i + 1]
        out.append(str(pref[r] - pref[l - 1]))
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


main()
