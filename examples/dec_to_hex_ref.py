import sys


def main() -> None:
    n = int(sys.stdin.read().strip())
    sys.stdout.write(format(n, "X") + "\n")


main()
