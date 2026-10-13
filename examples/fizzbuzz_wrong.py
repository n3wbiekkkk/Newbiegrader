import sys
# BUG: ตัวเล็กหมด (fizz แทน Fizz) + สะกด FizzBuzz ผิดเป็น Fizzbuzz
def main():
    n = int(sys.stdin.read().strip())
    for i in range(1, n + 1):
        if i % 15 == 0:
            print("Fizzbuzz")
        elif i % 3 == 0:
            print("fizz")
        elif i % 5 == 0:
            print("buzz")
        else:
            print(i)
main()
