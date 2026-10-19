#include "Probe.h"
#include <fenv.h>
#include <float.h>
#include <math.h>

#pragma STDC FENV_ACCESS ON

bool mathChecks() {
    volatile double half = 0.5, two = 2.0, pi = 3.14159265358979323846;
    bool passed = check(fabs(sin(pi / 6) - half) < 2e-15 &&
                        fabs(cos(pi / 3) - half) < 2e-15 &&
                        fabs(tan(pi / 4) - 1.0) < 2e-15, "math_double_trigonometry");
    passed &= check(fabs(sqrt(two) - 1.4142135623730951) < 2e-15 &&
                    hypot(3.0, 4.0) == 5.0 && pow(3.0, 3.0) == 27.0, "math_double_roots_power");
    passed &= check(fabs(log(exp(half)) - half) < 2e-15 &&
                    log2(8.0) == 3.0 && exp2(3.0) == 8.0 &&
                    fabs(expm1(log1p(half)) - half) < 2e-15, "math_double_log_exp");
    volatile float value = 0.5f;
    passed &= check(fabsf(sinf(value) - 0.4794255386f) < 2e-7f &&
                    fabsf(logf(expf(value)) - value) < 2e-7f &&
                    powf(2.0f, 5.0f) == 32.0f && sqrtf(2.25f) == 1.5f, "math_float_optimized");
    volatile double zero = 0.0, negative = -1.0;
    double nan = sqrt(negative), infinity = log(zero);
    passed &= check(isnan(nan) && isinf(infinity) && signbit(infinity) &&
                    signbit(sqrt(-zero)) && !signbit(fabs(-zero)) &&
                    fmax(nan, two) == two && nextafter(1.0, two) == 0x1.0000000000001p0,
                    "math_special_values");
    volatile long double one = 1.0L, precise = one + 0x1p-100L;
    passed &= check(sizeof(long double) == 16 && LDBL_MANT_DIG == 113 && precise > one &&
                    static_cast<double>(precise) == 1.0 &&
                    nextafterl(one, 2.0L) == one + 0x1p-112L, "math_binary128_precision");
    volatile long double x = 1.25L;
    passed &= check(fabsl(expl(logl(x)) - x) < 1e-32L &&
                    sqrtl(4.0L) == 2.0L && powl(2.0L, 10.0L) == 1024.0L &&
                    fabsl(hypotl(3.0L, 4.0L) - 5.0L) < 1e-32L, "math_binary128_functions");
    volatile long double angles[] = {0.0L, -0.0L, 0.25L, 1.0L, 2.0L, 3.0L, 4.0L,
                                    -1.0L, -2.0L, -3.0L, -4.0L, 1.0e10L, -1.0e10L};
    bool reduced = true;
    for (long double angle : angles) {
        long double sine = nanl(""), cosine = nanl("");
        sincosl(angle, &sine, &cosine);
        reduced &= fabsl(sine - sinl(angle)) < 1e-31L && fabsl(cosine - cosl(angle)) < 1e-31L;
    }
    passed &= check(reduced, "math_binary128_sincosl_reduction");
    fenv_t saved;
    bool environment = fegetenv(&saved) == 0;
    volatile double fraction = 1.75;
    environment &= fesetround(FE_DOWNWARD) == 0 && nearbyint(fraction) == 1.0 && lrint(fraction) == 1;
    environment &= fesetround(FE_UPWARD) == 0 && nearbyint(fraction) == 2.0 && lrint(fraction) == 2;
    environment &= fesetround(FE_TONEAREST) == 0;
    passed &= check(environment, "math_rounding_modes");
    bool exceptions = feclearexcept(FE_ALL_EXCEPT) == 0;
    volatile double invalid = sqrt(negative);
    exceptions &= isnan(invalid) && (fetestexcept(FE_INVALID) & FE_INVALID) != 0;
    exceptions &= feclearexcept(FE_ALL_EXCEPT) == 0 && fetestexcept(FE_ALL_EXCEPT) == 0;
    passed &= check(exceptions && fesetenv(&saved) == 0, "math_floating_exceptions");
    emit("math_long_double_bits=%d\n", LDBL_MANT_DIG);
    return passed;
}
