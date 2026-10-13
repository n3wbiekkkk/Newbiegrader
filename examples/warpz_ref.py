import sys


def main() -> None:
    data = sys.stdin.read().strip().split()
    if not data:
        return
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    reach = 1
    for i in range(1, n + 1):
        if i > reach:
            print("NO")
            return
        reach = max(reach, i + a[i - 1])
        if reach > n:
            print("YES")
            return
    print("NO")


main()
