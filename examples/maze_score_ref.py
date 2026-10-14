import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    g = [data[1 + i * n:1 + (i + 1) * n] for i in range(n)]
    r, c = data[1 + n * n], data[2 + n * n]
    NEG = -10 ** 18
    dp = [[NEG] * (c + 1) for _ in range(r + 1)]
    for i in range(r + 1):
        for j in range(c + 1):
            if i == 0 and j == 0:
                dp[i][j] = g[0][0]
            else:
                best = NEG
                if i > 0:
                    best = max(best, dp[i - 1][j])
                if j > 0:
                    best = max(best, dp[i][j - 1])
                dp[i][j] = best + g[i][j]
    sys.stdout.write(str(dp[r][c]) + "\n")


main()
