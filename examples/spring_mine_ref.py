import sys
from collections import deque


def main() -> None:
    data = sys.stdin.read().split()
    if len(data) < 3:
        return
    n, m, p = int(data[0]), int(data[1]), int(data[2])
    grid = data[3:3 + n]
    INF = 10 ** 9
    # dist[x][y][potions_left][has_key]
    dist = [[[[INF] * 2 for _ in range(p + 1)] for _ in range(m)] for _ in range(n)]
    dist[0][0][p][0] = 0
    if grid[0][0] == "K":
        dist[0][0][p][1] = 0
    dq = deque([(0, 0, p, 0 if grid[0][0] != "K" else 1)])
    while dq:
        x, y, pot, key = dq.popleft()
        d = dist[x][y][pot][key]
        if grid[x][y] == "T" and key:
            sys.stdout.write(str(d) + "\n")
            return
        nd = d + 1
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < n and 0 <= ny < m):
                continue
            cell = grid[nx][ny]
            npot = pot
            if cell == "#":
                if pot == 0:
                    continue
                npot = pot - 1
            nkey = key or (cell == "K")
            if dist[nx][ny][npot][nkey] > nd:
                dist[nx][ny][npot][nkey] = nd
                dq.append((nx, ny, npot, nkey))
    # guaranteed solvable; fallback reports best T-with-key distance found
    ans = min(dist[x][y][pot][1]
              for x in range(n) for y in range(m) if grid[x][y] == "T"
              for pot in range(p + 1))
    sys.stdout.write(str(ans if ans < INF else -1) + "\n")


main()
