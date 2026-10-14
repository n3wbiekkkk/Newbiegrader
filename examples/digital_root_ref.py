import sys


def main() -> None:
    x = int(sys.stdin.read().strip())
    while x >= 10:
        x = sum(map(int, str(x)))
    sys.stdout.write(str(x) + "\n")


main()
