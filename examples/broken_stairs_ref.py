import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n, k = data[0], data[1]
    broken = set(data[2:2 + k])
    NEG = -1
    dp = [NEG] * (n + 1)
    dp[0] = 1
    for i in range(n + 1):
        if i in broken:
            dp[i] = NEG
            continue
        if i == 0:
            continue
        if dp[i] == NEG:
            dp[i] = 0
        for s in (1, 2, 3):
            if i - s >= 0 and dp[i - s] != NEG and dp[i - s] > 0:
                if dp[i] == NEG:
                    dp[i] = 0
                dp[i] += dp[i - s]
    ans = dp[n] if dp[n] != NEG else 0
    sys.stdout.write(str(ans) + "\n")


main()
