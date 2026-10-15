import sys


def main() -> None:
    data = sys.stdin.read().split()
    if not data:
        return
    n = int(data[0])
    codes, scores = [], []
    idx = 1
    for _ in range(n):
        codes.append(data[idx])
        scores.append(int(data[idx + 1]))
        idx += 2
    total = sum(scores)
    passed = [c for c, s in zip(codes, scores) if s * n >= total]
    out = [str(len(passed))] + passed
    sys.stdout.write("\n".join(out) + "\n")


main()
