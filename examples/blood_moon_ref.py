import sys


def main() -> None:
    data = sys.stdin.buffer.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    l, r = 0, n - 1
    while l < r:
        if (a[l] + a[r]) % 2 == 0:
            a[l], a[r] = a[r], a[l]
        else:
            a[l] += 1
            a[r] += 1
        l += 1
        r -= 1
    sys.stdout.write(" ".join(map(str, a)) + ("\n" if a else ""))


main()
