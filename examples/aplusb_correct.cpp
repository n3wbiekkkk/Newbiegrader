// A+B correct (C++) — ใช้ long long ไม่งั้นแตก test 10^18
#include <iostream>
using namespace std;
int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    long long a, b;
    if (!(cin >> a >> b)) return 0;
    cout << a + b << "\n";
    return 0;
}
