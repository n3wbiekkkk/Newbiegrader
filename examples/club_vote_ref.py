import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    votes = data[1:1 + n]
    freq = [0] * 1001
    for v in votes:
        if 1 <= v <= 1000:
            freq[v] += 1
    best, best_c = 1, freq[1]
    for cid in range(2, 1001):
        if freq[cid] > best_c:
            best, best_c = cid, freq[cid]
    sys.stdout.write(f"{best} {best_c}\n")


main()
