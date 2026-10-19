#include <hidl/HidlTransportSupport.h>

bool registerGuestMtdStorage();

int main() {
    android::hardware::configureRpcThreadpool(2, true);
    if (!registerGuestMtdStorage()) return 1;
    android::hardware::joinRpcThreadpool();
}
