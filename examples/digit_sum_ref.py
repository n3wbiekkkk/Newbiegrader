import sys


def main() -> None:
    x = int(sys.stdin.read().strip())
    sys.stdout.write(str(sum(map(int, str(x)))) + "\n")


main()
