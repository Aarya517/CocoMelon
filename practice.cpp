#include<iostream>
#include<vector>
using namespace std;

class Solution
{
public:
    int getMinDiff(vector<int> &arr, int k)
    {
    }
};

int main()
{
    cout << "enter number of elements in an array: ";
    int n;
    cin >> n;
    vector<int> arr(n);
    cout << "Enter elements: ";
    for (int i = 0; i < n; i++)
    {
        cin >> arr[i];
    }
    cout << "enter height to increase or decrease: ";
    int k;
    cin >> k;
    Solution s;
    cout << "Maximum Profit: ";
    cout << s.getMinDiff(arr, k);

    return 0;
}
