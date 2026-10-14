import sys


def hanoi(n: int, src: int, aux: int, dst: int, out: list[str]) -> None:
    if n == 0:
        return
    hanoi(n - 1, src, dst, aux, out)
    out.append(f"Move disc {n} from {src} to {dst}")
    hanoi(n - 1, aux, src, dst, out)


def main() -> None:
    n = int(sys.stdin.read().strip())
    out: list[str] = []
    hanoi(n, 1, 2, 3, out)
    out.append(f"Total moves: {(1 << n) - 1}")
    sys.stdout.write("\n".join(out) + "\n")


main()
