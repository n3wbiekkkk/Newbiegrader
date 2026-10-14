import sys
from itertools import combinations


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n, s = data[0], data[1]
    prices = data[2:2 + n]
    ways = 0
    best = None
    for r in range(n + 1):
        for combo in combinations(range(n), r):
            if sum(prices[i] for i in combo) == s:
                ways += 1
                if best is None or r < best:
                    best = r
    out = [str(ways), str(best if best is not None else -1)]
    sys.stdout.write("\n".join(out) + "\n")


main()
