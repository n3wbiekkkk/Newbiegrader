import sys


def main() -> None:
    data = sys.stdin.read().split()
    if not data:
        return
    n = int(data[0])
    out = []
    for i in range(1, n + 1):
        s = data[i].strip()
        if s.startswith("#"):
            s = s[1:]
        if len(s) == 3:
            s = s[0] * 2 + s[1] * 2 + s[2] * 2
        out.append(f"{int(s[0:2], 16)} {int(s[2:4], 16)} {int(s[4:6], 16)}")
    sys.stdout.write("\n".join(out) + "\n")


main()
