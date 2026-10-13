import sys
def main():
    data = sys.stdin.read().strip().split()
    a, b = int(data[0]), int(data[1])
    # BUG: ใช้ int 32-bit mindset / ลืมเคสใหญ่ + พิมพ์มีช่องว่างเกิน
    print(a + b, end="  \n")  # trailing spaces -> token checker รอด แต่ --strict แตก
main()
