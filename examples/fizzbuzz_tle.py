import sys
import time
def main():
    n = int(sys.stdin.read().strip())
    # BUG โหด: O(n^2) — concat string ทีละบรรทัดแบบโง่ๆ + sleep แกล้งช้าใน test ใหญ่
    s = ""
    for i in range(1, n + 1):
        if i % 15 == 0:
            s += "FizzBuzz\n"
        elif i % 3 == 0:
            s += "Fizz\n"
        elif i % 5 == 0:
            s += "Buzz\n"
        else:
            s += str(i) + "\n"
        if n > 50000:
            time.sleep(0.00005)  # โดน TLE ที่ test 05 แน่นอน
    sys.stdout.write(s)
main()
