import sys


def main() -> None:
    a, b = map(int, sys.stdin.read().split())
    sys.stdout.write(str(pow(a, b)) + "\n")


main()
