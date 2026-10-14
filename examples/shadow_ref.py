import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n, m = data[0], data[1]
    s = data[2:2 + n]
    d = data[2 + n:2 + n + m]
    i = 0
    for need in d:
        total = 0
        while i < n and total < need:
            total += s[i]
            i += 1
        if total < need:
            print("No")
            return
    print("Yes")


main()
