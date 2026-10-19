# AOSP keyboard

The bundled keyboard is Android 10 AOSP LatinIME, package
com.android.inputmethod.latin, with its matching ARM64 libjni_latinime.so.
Both original files come from the audited Android 10 user-space image.
The APK and library are copied without binary changes.

LatinIME supports English and other Latin-alphabet languages, numbers and
symbols. Chinese input methods may be installed separately inside Android 10.
Existing valid keyboard selection and application data are preserved.

Source:
https://android.googlesource.com/platform/packages/inputmethods/LatinIME/+/android-10.0.0_r47/

The Android Open Source Project and contributors retain their copyright.
The upstream NOTICE, including Apache-2.0 and component notices, is reproduced
in LICENSE and shipped at /system/etc/a10vm-keyboard/LICENSE.
Original notices within the APK and dictionaries remain intact.

APK SHA-256:
d8353e848158226aa7e9fbec0ef9345b2d49adbafd2dc7688f2297cdccbe16b9

ARM64 JNI SHA-256:
8d82db1ba4c41b343d6d331516939084705a6c60301a55a29b17c3b4f0758f68

Source user-space image SHA-256:
fc10aa9478729b1795ede64c0f5b996759262dc6bb43271b19c7d88615a16373
