import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n, k = data[0], data[1]
    prices = sorted(data[2:2 + n])
    total, cnt = 0, 0
    for p in prices:
        if total + p > k:
            break
        total += p
        cnt += 1
    sys.stdout.write(str(cnt) + "\n")


main()
