import sys


def thai_time(n: int, s: str) -> str:
    if n < 1 or n > 12:
        return "invalid"
    if s == "AM":
        if n == 12:
            return "Thiang Khuen"
        if n <= 5:
            return f"Ti {n}"
        return f"{n} Mong Chao"
    if s == "PM":
        if n == 12:
            return "Thiang Whan"
        if n <= 3:
            return f"Bai {n}"
        if n <= 6:
            return f"{n} Mong Yen"
        return f"{n - 6} Thum"
    return "invalid"


def main() -> None:
    tok = sys.stdin.read().split()
    sys.stdout.write(thai_time(int(tok[0]), tok[1]) + "\n")


main()
