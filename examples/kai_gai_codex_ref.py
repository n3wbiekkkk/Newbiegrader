import sys


def decode(s: str) -> str:
    num_stack, str_stack = [], []
    cur_num = 0
    cur: list = []
    for ch in s:
        if ch.isdigit():
            cur_num = cur_num * 10 + int(ch)
        elif ch == "[":
            num_stack.append(cur_num)
            str_stack.append(cur)
            cur_num = 0
            cur = []
        elif ch == "]":
            rep = num_stack.pop()
            prev = str_stack.pop()
            seg = "".join(cur)
            cur = prev + [seg * rep]
        else:
            cur.append(ch)
    return "".join(cur)


def count_word(t: str, lead: str) -> tuple:
    n = len(t)
    cnt = 0
    longest = 0
    i = 0
    while i < n:
        if (t[i] == lead and i + 2 < n
                and t[i + 1] == "A" and t[i + 2] == "I"):
            j = i + 2
            while j < n and t[j] == "I":
                j += 1
            cnt += 1
            if j - (i + 2) > longest:
                longest = j - (i + 2)
            i = j
        else:
            i += 1
    return cnt, longest


def main() -> None:
    s = sys.stdin.read().split("\n")[0].strip()
    text = decode(s)
    up = text.upper()
    kc, kt = count_word(up, "K")
    gc, gt = count_word(up, "G")
    out = [str(len(text))]
    if kc or gc:
        out.append(f"{kc} {kt}")
        out.append(f"{gc} {gt}")
    elif "K" in up or "G" in up:
        idx = next(i for i, ch in enumerate(up) if ch in ("K", "G"))
        out.append(text[:idx + 1] + "I" * (len(text) - idx - 1))
    else:
        pat = "KAIGAI"
        out.append("".join(pat[i % 6] for i in range(len(text))))
    sys.stdout.write("\n".join(out) + "\n")


main()
