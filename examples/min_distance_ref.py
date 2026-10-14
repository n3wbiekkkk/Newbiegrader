import sys


def main() -> None:
    data = sys.stdin.buffer.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    m = a[n // 2]
    tot = 0
    for x in a:
        tot += abs(x - m)
    print(tot)


main()
