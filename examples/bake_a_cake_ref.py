import sys
from fractions import Fraction


def solve(lines: list[str]) -> tuple[int, str]:
    sep = next(i for i, ln in enumerate(lines) if ln.strip() == "-1")
    need: dict[str, Fraction] = {}
    order: list[str] = []
    for ln in lines[:sep]:
        if not ln.strip():
            continue
        amt_s, name = ln.split(None, 1)
        need[name] = Fraction(amt_s)
        order.append(name)
    have: dict[str, Fraction] = {}
    for ln in lines[sep + 1:]:
        if not ln.strip():
            continue
        amt_s, name = ln.split(None, 1)
        have[name] = Fraction(amt_s)
    best = None
    best_name = None
    for name in order:
        nd = need[name]
        if nd <= 0:
            continue  # needs nothing: never the limiter
        cakes = have.get(name, Fraction(0)) // nd
        if best is None or cakes < best:
            best = cakes
            best_name = name
    if best is None:
        best, best_name = 0, order[0]
    return int(best), best_name


def main() -> None:
    best, name = solve(sys.stdin.read().splitlines())
    print(f"{best} cake(s)")
    print(f"You should buy more {name}")


main()
