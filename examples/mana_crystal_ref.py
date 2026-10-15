import sys
from itertools import accumulate


def main() -> None:
    data = sys.stdin.buffer.read().split()
    if not data:
        return
    n = int(data[0])
    k = int(data[-1])
    vals = list(map(int, data[1:1 + n * n]))
    m = n // k
    if k == 1:
        # Each block is a single cell: the average is the value itself.
        out = "\n".join(
            " ".join(f"{v}.00" for v in vals[i * n:(i + 1) * n])
            for i in range(n))
        sys.stdout.write(out + "\n")
        return
    grid = [vals[i * n:(i + 1) * n] for i in range(n)]
    # Row prefix sums in C speed; each block then costs k subtractions.
    pref = [[0] + list(accumulate(row)) for row in grid]
    kk = k * k
    out_lines = []
    for br in range(m):
        r0 = br * k
        cells = []
        for bc in range(m):
            c0 = bc * k
            c1 = c0 + k
            s = 0
            for r in range(r0, r0 + k):
                s += pref[r][c1] - pref[r][c0]
            cells.append(f"{s / kk:.2f}")
        out_lines.append(" ".join(cells))
    sys.stdout.write("\n".join(out_lines) + "\n")


main()
