import sys
from collections import deque


def main() -> None:
    data = sys.stdin.read().split()
    if not data:
        return
    r, c = int(data[0]), int(data[1])
    grid = data[2:2 + r]
    sr = sc = er = ec = -1
    for i in range(r):
        for j in range(c):
            ch = grid[i][j]
            if ch == "S":
                sr, sc = i, j
            elif ch == "E":
                er, ec = i, j
    dist = [[-1] * c for _ in range(r)]
    dist[sr][sc] = 0
    dq = deque([(sr, sc)])
    while dq:
        i, j = dq.popleft()
        if i == er and j == ec:
            break
        nd = dist[i][j] + 1
        if i > 0 and grid[i - 1][j] != "#" and dist[i - 1][j] < 0:
            dist[i - 1][j] = nd
            dq.append((i - 1, j))
        if i + 1 < r and grid[i + 1][j] != "#" and dist[i + 1][j] < 0:
            dist[i + 1][j] = nd
            dq.append((i + 1, j))
        if j > 0 and grid[i][j - 1] != "#" and dist[i][j - 1] < 0:
            dist[i][j - 1] = nd
            dq.append((i, j - 1))
        if j + 1 < c and grid[i][j + 1] != "#" and dist[i][j + 1] < 0:
            dist[i][j + 1] = nd
            dq.append((i, j + 1))
    sys.stdout.write(str(dist[er][ec]) + "\n")


main()
