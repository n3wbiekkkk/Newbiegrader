import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n, w = data[0], data[1]
    a = sorted(data[2:2 + n])
    i, j = 0, n - 1
    boats = 0
    while i <= j:
        if a[i] + a[j] <= w:
            i += 1
        j -= 1
        boats += 1
    sys.stdout.write(str(boats) + "\n")


main()
