import sys


def is_pal(x: int) -> bool:
    s = str(x)
    return s == s[::-1]


def main() -> None:
    a, b = map(int, sys.stdin.read().split())
    found = [n for n in range(a, b + 1) if is_pal(n) and is_pal(n * n)]
    out = [str(len(found))]
    if found:
        out.append(" ".join(map(str, found)))
    sys.stdout.write("\n".join(out) + "\n")


main()
