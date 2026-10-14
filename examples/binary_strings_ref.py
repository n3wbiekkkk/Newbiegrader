import sys


def main() -> None:
    n = int(sys.stdin.read().strip())
    out = []
    def gen(cur: str) -> None:
        if len(cur) == n:
            out.append(cur)
            return
        gen(cur + "0")
        if not cur or cur[-1] != "1":
            gen(cur + "1")
    gen("")
    out.append(str(len(out)))
    sys.stdout.write("\n".join(out) + "\n")


main()
