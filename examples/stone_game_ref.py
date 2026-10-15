import sys


def min_left(board: str, memo: dict) -> int:
    if board in memo:
        return memo[board]
    b = list(board)
    best = sum(1 for ch in b if ch == "o")
    for i in range(10):
        # C jumps over B into A (leftward): A empty, B and C occupied
        if b[i] == "-" and b[i + 1] == "o" and b[i + 2] == "o":
            b[i], b[i + 1], b[i + 2] = "o", "-", "-"
            r = min_left("".join(b), memo)
            if r < best:
                best = r
            b[i], b[i + 1], b[i + 2] = "-", "o", "o"
        # mirror (rightward): A occupied jumps over B into empty C
        if b[i] == "o" and b[i + 1] == "o" and b[i + 2] == "-":
            b[i], b[i + 1], b[i + 2] = "-", "-", "o"
            r = min_left("".join(b), memo)
            if r < best:
                best = r
            b[i], b[i + 1], b[i + 2] = "o", "o", "-"
    memo[board] = best
    return best


def main() -> None:
    data = sys.stdin.read().split()
    if not data:
        return
    n = int(data[0])
    boards = data[1:1 + n]
    out = [str(min_left(b, {})) for b in boards]
    sys.stdout.write("\n".join(out) + "\n")


main()
