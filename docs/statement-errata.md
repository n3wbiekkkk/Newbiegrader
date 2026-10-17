# Statement errata

## 2026-10-17 — #48 Forest Fire Spread (`forest_fire_spread`)

Each input grid row contains **C integers separated by spaces**, rather than a
single digit string. This applies to public samples and hidden test inputs.
The reference input parser follows the same format. The rules, limits, problem
number, test cell values and expected outputs are unchanged.

Correct first sample input:

```text
3 3
0 1 0
1 2 1
0 1 0
1
```

Output remains compact (no spaces between cells):

```text
020
202
020
```

The first sample's corner cells are empty, so its explanation now describes
them as empty rather than trees. The statement PDF and Supabase problem assets
must be refreshed together with the test manifest and test-set hash. Problem
packages and reference solutions remain private and are not versioned here.
