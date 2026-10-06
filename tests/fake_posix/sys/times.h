#ifndef FAKE_POSIX_SYS_TIMES_H
#define FAKE_POSIX_SYS_TIMES_H
/* MinGW omits this POSIX header. The unsupported _times syscall uses only an
   opaque argument, so native firmware tests do not need a clock emulation. */
struct tms;
#endif
