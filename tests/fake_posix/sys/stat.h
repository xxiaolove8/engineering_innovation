#ifndef FAKE_POSIX_SYS_STAT_H
#define FAKE_POSIX_SYS_STAT_H
/* Firmware syscall tests need only the st_mode field. Avoid the host CRT's
   different _read/_write/_stat prototypes when compiling bare-metal stubs. */
struct stat { unsigned st_mode; };
#define S_IFCHR 0020000U
#endif
