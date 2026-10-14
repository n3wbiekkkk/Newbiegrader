import sys

W = (13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2)


def check(code: str) -> bool:
    s = sum(int(d) * w for d, w in zip(code[:12], W))
    return (11 - (s % 11)) % 10 == int(code[12])


def main() -> None:
    lines = sys.stdin.read().split()
    q = int(lines[0])
    out = []
    for code in lines[1:1 + q]:
        if "?" not in code:
            out.append("VALID" if check(code) else "INVALID")
        else:
            pos = code.index("?")
            ok = [str(d) for d in range(10)
                  if check(code[:pos] + str(d) + code[pos + 1:])]
            out.append(" ".join(ok) if ok else "NONE")
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


main()
