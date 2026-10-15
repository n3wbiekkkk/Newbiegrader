import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    if not data:
        return
    h = data[1:1 + data[0]]
    left, right = 0, len(h) - 1
    lmax = rmax = 0
    total = 0
    while left < right:
        if h[left] < h[right]:
            if h[left] >= lmax:
                lmax = h[left]
            else:
                total += lmax - h[left]
            left += 1
        else:
            if h[right] >= rmax:
                rmax = h[right]
            else:
                total += rmax - h[right]
            right -= 1
    sys.stdout.write(str(total) + "\n")


main()
