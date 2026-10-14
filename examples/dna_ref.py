import sys

COMP = {"A": "T", "T": "A", "C": "G", "G": "C"}


def main() -> None:
    s = sys.stdin.read().strip()
    if not s:
        return
    sys.stdout.write("".join(COMP[ch] for ch in reversed(s)) + "\n")


main()
