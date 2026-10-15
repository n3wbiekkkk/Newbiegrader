import sys


def main() -> None:
    data = list(map(int, sys.stdin.read().split()))
    if len(data) < 2:
        return
    n, k = data[0], data[1]
    ans = 0
    for i in range(2, n + 1):
        ans = (ans + k) % i
    sys.stdout.write(str(ans + 1) + "\n")


main()
