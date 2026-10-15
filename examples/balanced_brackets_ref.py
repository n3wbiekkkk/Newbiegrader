import sys

PAIRS = {")": "(", "]": "[", "}": "{", ">": "<"}


def main() -> None:
    text = sys.stdin.read().split("\n")
    if text and text[-1] == "":
        text.pop()
    out = []
    for line in text:
        stack = []
        ok = True
        for ch in line:
            if ch in "([<{":
                stack.append(ch)
            elif ch in PAIRS:
                if not stack or stack.pop() != PAIRS[ch]:
                    ok = False
                    break
        out.append("Yes" if ok and not stack else "No")
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


main()
