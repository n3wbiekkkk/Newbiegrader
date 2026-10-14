import sys


def main() -> None:
    lines = sys.stdin.read().split()
    r, c = int(lines[0]), int(lines[1])
    g = [lines[2 + i] for i in range(r)]
    seen = [[False] * c for _ in range(r)]
    islands = 0
    biggest = 0
    for i in range(r):
        for j in range(c):
            if g[i][j] == "#" and not seen[i][j]:
                islands += 1
                size, stack = 0, [(i, j)]
                seen[i][j] = True
                while stack:
                    x, y = stack.pop()
                    size += 1
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < r and 0 <= ny < c:
                            if g[nx][ny] == "#" and not seen[nx][ny]:
                                seen[nx][ny] = True
                                stack.append((nx, ny))
                biggest = max(biggest, size)
    sys.stdout.write(f"{islands} {biggest}\n")


main()
