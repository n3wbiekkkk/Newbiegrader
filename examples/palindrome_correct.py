import sys
def main():
    # อ่านทั้ง input, ตัดแค่ \n ท้ายไฟล์ (ไม่ strip ช่องว่าง — ช่องว่างคือตัวอักษร!)
    data = sys.stdin.read().splitlines()
    s = data[0] if data else ""
    # empty input -> empty string -> YES
    print("YES" if s == s[::-1] else "NO")
main()
