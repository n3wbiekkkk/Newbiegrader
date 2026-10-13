import sys


def main() -> None:
    data = sys.stdin.buffer.read().split()
    if not data:
        return
    it = iter(data)
    n = int(next(it))
    grid = [[int(next(it)) for _ in range(n)] for _ in range(n)]
    k = int(next(it))
    m = n // k
    kk = k * k
    out_lines = []
    for br in range(m):
        row = []
        for bc in range(m):
            s = 0
            for i in range(br * k, br * k + k):
                grow = grid[i]
                for j in range(bc * k, bc * k + k):
                    s += grow[j]
            row.append(repr(s / kk))
        out_lines.append(" ".join(row))
    sys.stdout.write("\n".join(out_lines) + "\n")


main()
