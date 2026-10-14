import sys


def main() -> None:
    s = sys.stdin.read().strip()
    sys.stdout.write(str(sum(int(c) for c in s if c.isdigit())) + "\n")


main()
