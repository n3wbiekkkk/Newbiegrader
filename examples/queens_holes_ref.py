import sys


def main() -> None:
    lines = sys.stdin.read().split()
    n = int(lines[0])
    board = [lines[1 + i] for i in range(n)]
    cols = [False] * n
    d1 = [False] * (2 * n)
    d2 = [False] * (2 * n)
    cur = [0] * n
    count = 0
    best = None

    def place(r: int) -> None:
        nonlocal count, best
        if r == n:
            count += 1
            if best is None:
                best = list(cur)
            return
        for c_ in range(n):
            if board[r][c_] == "#" or cols[c_] or d1[r - c_ + n] or d2[r + c_]:
                continue
            cols[c_] = d1[r - c_ + n] = d2[r + c_] = True
            cur[r] = c_ + 1
            place(r + 1)
            cols[c_] = d1[r - c_ + n] = d2[r + c_] = False

    place(0)
    out = [str(count), " ".join(map(str, best)) if best else "NONE"]
    sys.stdout.write("\n".join(out) + "\n")


main()
