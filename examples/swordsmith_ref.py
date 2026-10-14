import heapq
import sys


def main() -> None:
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    heap = data[1:1 + n]
    heapq.heapify(heap)
    total = 0
    while len(heap) > 1:
        x = heapq.heappop(heap)
        y = heapq.heappop(heap)
        total += x + y
        heapq.heappush(heap, x + y)
    sys.stdout.write(str(total) + "\n")


main()
