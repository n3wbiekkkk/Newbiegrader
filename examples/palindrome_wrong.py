import sys
def main():
    # BUG: ดันไป .lower() + strip spaces — สอบตก test Aa และ 'nurses run'
    s = sys.stdin.read().strip().lower().replace(" ", "")
    print("YES" if s == s[::-1] else "NO")
main()
