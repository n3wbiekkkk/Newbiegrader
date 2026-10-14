import sys


def main() -> None:
    a, b = map(int, sys.stdin.read().split())
    memo = {1: 0}
    best_n, best_s = a, -1
    for n in range(a, b + 1):
        x, cnt, seen = n, 0, []
        while x != 1 and x not in memo:
            seen.append(x)
            x = x // 2 if x % 2 == 0 else 3 * x + 1
            cnt += 1
        base = memo.get(x, 0)
        total = cnt + base
        for i, v in enumerate(seen):
            if v not in memo:
                memo[v] = total - i
        memo[n] = total
        if total > best_s:
            best_n, best_s = n, total
    sys.stdout.write(f"{best_n} {best_s}\n")


main()
