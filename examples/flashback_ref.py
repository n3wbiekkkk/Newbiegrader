import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n, k = data[0], data[1]
    a = data[2:2 + n]
    window = sum(a[:k])
    best_min, best_min_day = window, 1
    best_max, best_max_day = window, 1
    for start in range(2, n - k + 2):
        window += a[start + k - 2] - a[start - 2]
        if window < best_min:
            best_min, best_min_day = window, start
        if window > best_max:
            best_max, best_max_day = window, start
    sys.stdout.write(f"{best_min} {best_min_day}\n{best_max} {best_max_day}\n")


main()
