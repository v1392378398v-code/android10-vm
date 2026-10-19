#include <complex.h>
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <unistd.h>

static bool result(const char* name, bool passed) {
    char line[128];
    int length = snprintf(line, sizeof(line), "CHECK\t%s\t%d\n", name, passed);
    return length > 0 && length < sizeof(line) && write(STDOUT_FILENO, line, length) == length && passed;
}

bool complexChecks(void) {
    volatile double pi = 3.14159265358979323846;
    double complex exp_value = cexp(I * pi), root = csqrt(-4.0 + 0.0 * I);
    double complex power = cpow(1.0 + I, 2.0);
    bool passed = result("math_complex_double", fabs(creal(exp_value) + 1.0) < 2e-15 &&
                        fabs(cimag(exp_value)) < 2e-15 && creal(root) == 0.0 &&
                        cimag(root) == 2.0 && cabs(power - 2.0 * I) < 2e-15);
    volatile long double complex long_value = 1.0L + 2.0L * I;
    long double complex square = cpowl(long_value, 2.0L);
    long double power_error = cabsl(square - (-3.0L + 4.0L * I));
    long double root_error = cabsl(csqrtl(long_value) * csqrtl(long_value) - long_value);
    char diagnostic[256];
    int length = snprintf(diagnostic, sizeof(diagnostic),
                          "complex_power_error=%.36Lg\ncomplex_root_error=%.36Lg\n", power_error, root_error);
    if (length <= 0 || length >= sizeof(diagnostic) ||
        write(STDOUT_FILENO, diagnostic, length) != length) return false;
    passed &= result("math_complex_binary128", power_error < 1e-31L && root_error < 1e-31L);
    return passed;
}
