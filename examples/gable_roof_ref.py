import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    if len(data) < 2:
        return
    n, m = data[0], data[1]
    a = data[2:2 + n]
    mid = m // 2
    base = a[0]
    target = [base + i if i <= mid else base + (m - 1 - i) for i in range(m)]
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        ai = a[i - 1]
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if ai == target[j - 1] else 1
            c = prev[j - 1] + cost
            d = prev[j] + 1
            e = cur[j - 1] + 1
            if d < c:
                c = d
            if e < c:
                c = e
            cur[j] = c
        prev = cur
    sys.stdout.write(str(prev[m]) + "\n")


main()
