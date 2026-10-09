// Check build only, macOS only (check.py ASSERT_SHIM): found before the SDK's <assert.h>.
// The SDK's assert(e) expands to `!(e)`, and those parentheses hide `assert(a = b)` from
// -Wparentheses. glibc's expands to `if (e)`, which warns. This redefines assert the glibc way so
// both platforms catch an assert that changes state (it would vanish under -DNDEBUG in prod).
// No include guard, like the real one: <assert.h> may be re-included with NDEBUG toggled.
#include_next <assert.h>
#ifndef NDEBUG
#undef assert
#define assert(e) __extension__({ if (e) {} else __assert_rtn(__func__, __FILE__, __LINE__, #e); })
#endif
