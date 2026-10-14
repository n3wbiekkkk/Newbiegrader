import sys


def rotate(mat: list[list[int]], k: int) -> list[list[int]]:
    m, n = len(mat), len(mat[0])
    if k == 1:
        return [[mat[m - 1 - j][i] for j in range(m)] for i in range(n)]
    if k == 2:
        return [[mat[m - 1 - i][n - 1 - j] for j in range(n)] for i in range(m)]
    return [[mat[j][n - 1 - i] for j in range(m)] for i in range(n)]


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    m, n, k = data[0], data[1], data[2]
    vals = data[3:3 + m * n]
    mat = [vals[i * n:(i + 1) * n] for i in range(m)]
    out = rotate(mat, k)
    sys.stdout.write("\n".join(" ".join(map(str, row)) for row in out) + "\n")


main()
