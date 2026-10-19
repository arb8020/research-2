#include_next <assert.h>
#ifndef NDEBUG
#undef assert
#define assert(e) __extension__({ if (e) {} else __assert_rtn(__func__, __FILE__, __LINE__, #e); })
#endif
