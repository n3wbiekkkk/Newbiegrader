import sys


def main() -> None:
    data = sys.stdin.read().split()
    if not data:
        return
    it = iter(data)
    n = int(next(it))
    order, info = [], {}
    for _ in range(n):
        code = int(next(it))
        g, s, b = int(next(it)), int(next(it)), int(next(it))
        order.append(code)
        info[code] = (g, s, b)
    out = []
    for tok in it:
        q = int(tok)
        if q <= 0:
            out.append("good bye")
            break
        if q == 1001:
            m = max(v[0] for v in info.values())
            out.append(" ".join(str(c) for c in order if info[c][0] == m))
        elif q == 1002:
            m = max(v[1] for v in info.values())
            out.append(" ".join(str(c) for c in order if info[c][1] == m))
        elif q == 1003:
            m = max(v[2] for v in info.values())
            out.append(" ".join(str(c) for c in order if info[c][2] == m))
        elif q == 2000:
            m = max(sum(v) for v in info.values())
            out.append(" ".join(str(c) for c in order if sum(info[c]) == m))
        elif q == 3000:
            out.append(" ".join(str(c) for c in order if sum(info[c]) >= 1))
        elif q in info:
            g, s, b = info[q]
            out.append(f"{g} {s} {b} {g + s + b}")
        else:
            out.append("invalid code")
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


main()
