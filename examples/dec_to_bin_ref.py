import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    a = data[1:1 + n]
    sys.stdout.write("\n".join(bin(x)[2:] for x in a) + "\n")


main()
