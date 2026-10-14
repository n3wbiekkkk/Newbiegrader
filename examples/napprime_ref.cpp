#include <cstdio>
#include <iostream>
#include <vector>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    const int N = 1000000;
    vector<char> is_composite(N + 1, 0);
    vector<int> pref(N + 1, 0);
    for (int i = 2; i * 1LL * i <= N; i++)
        if (!is_composite[i])
            for (int j = i * i; j <= N; j += i) is_composite[j] = 1;
    for (int i = 1; i <= N; i++)
        pref[i] = pref[i - 1] + (i >= 2 && !is_composite[i]);
    int l, r;
    if (!(cin >> l >> r)) return 0;
    if (l > r) {
        int t = l;
        l = r;
        r = t;
    }
    printf("%d\n", pref[r] - (l > 0 ? pref[l - 1] : 0));
    return 0;
}
