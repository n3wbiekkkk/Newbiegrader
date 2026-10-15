import sys


def main() -> None:
    data = sys.stdin.read().split()
    if not data:
        return
    n, t = int(data[0]), int(data[1])
    ids, totals = [], []
    idx = 2
    for _ in range(n):
        sid = data[idx]
        idx += 1
        scores = list(map(int, data[idx:idx + t]))
        idx += t
        totals.append(sum(scores) - min(scores))
        ids.append(sid)
    best = max(totals)
    out = [str(best)] + [sid for sid, tot in zip(ids, totals) if tot == best]
    sys.stdout.write("\n".join(out) + "\n")


main()
