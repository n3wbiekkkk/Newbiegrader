import math
import sys


def sieve(n: int) -> list[int]:
    bs = bytearray(b"\x01") * (n + 1)
    bs[:2] = b"\x00\x00"
    for i in range(2, math.isqrt(n) + 1):
        if bs[i]:
            bs[i * i:n + 1:i] = b"\x00" * ((n - i * i) // i + 1)
    return [i for i, v in enumerate(bs) if v]


_PRIMES = sieve(10 ** 6)


def distinct_prime_factors(n: int) -> list[int]:
    res = []
    for p in _PRIMES:
        if p * p > n:
            break
        if n % p == 0:
            res.append(p)
            while n % p == 0:
                n //= p
    if n > 1:
        res.append(n)
    return res


def main() -> None:
    n = int(sys.stdin.read().strip())
    if n <= 1:
        print(0)
        return
    facs = distinct_prime_factors(n)
    out = [str(len(facs))]
    out += [str(p) for p in facs]
    sys.stdout.write("\n".join(out) + "\n")


main()
