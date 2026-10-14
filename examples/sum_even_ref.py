import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    a = data[1:1 + n]
    sys.stdout.write(str(sum(x for x in a if x % 2 == 0)) + "\n")


main()
