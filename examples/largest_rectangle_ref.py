import sys


def largest(h: list[int]) -> int:
    st: list[int] = []
    best = 0
    for i, x in enumerate(h + [0]):
        while st and h[st[-1]] >= x:
            height = h[st.pop()]
            left = st[-1] + 1 if st else 0
            area = height * (i - left)
            if area > best:
                best = area
        st.append(i)
    return best


def main() -> None:
    data = list(map(int, sys.stdin.read().split()))
    out = []
    i = 0
    while i < len(data):
        n = data[i]
        i += 1
        if n == 0:
            break
        h = data[i:i + n]
        i += n
        out.append(str(largest(h)))
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


main()
