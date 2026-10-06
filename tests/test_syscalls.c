#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <setjmp.h>

/* Keep the test's bare-metal environment and exit symbols out of the CRT. */
#ifdef environ
#undef environ
#endif
#define environ car_test_environ
#define _exit CarTestExit
#define _unlink CarTestUnlink
#include "../Core/Src/syscalls.c"

static jmp_buf exit_jump;
static int exit_test_armed;
void CarHw_EmergencyStop(void) {
  if (exit_test_armed) {
    exit_test_armed=0;
    longjmp(exit_jump,1);
  }
}

#ifdef TEST_IO_HOOKS
static int input_budget, output_budget, input_next;
static unsigned char written[8];
static unsigned written_count;
int __io_getchar(void) {
  return input_budget-- > 0 ? input_next++ : -1;
}
int __io_putchar(int ch) {
  if (output_budget-- <= 0) return -1;
  written[written_count++]=(unsigned char)ch;
  return ch;
}
#endif

int main(void) {
  char bytes[4]={'A',(char)0xFF,'C',0};
  struct stat status;
  for (int file=0; file<=2; ++file) {
    assert(_fstat(file,&status)==0 && status.st_mode==S_IFCHR);
    assert(_fstat(file,NULL)==-1 && errno==EFAULT);
    assert(_isatty(file)==1);
    assert(_close(file)==-1 && errno==ENOSYS);
    assert(_lseek(file,0,0)==-1 && errno==ESPIPE);
  }
  const int invalid_descriptors[]={-1,3,100};
  for (unsigned i=0U; i<sizeof(invalid_descriptors)/sizeof(invalid_descriptors[0]); ++i) {
    int file=invalid_descriptors[i];
    assert(_fstat(file,&status)==-1 && errno==EBADF);
    assert(_isatty(file)==0 && errno==EBADF);
    assert(_close(file)==-1 && errno==EBADF);
    assert(_lseek(file,0,0)==-1 && errno==EBADF);
  }
  assert(_stat(NULL,&status)==-1 && errno==EFAULT);
  assert(_stat("file",NULL)==-1 && errno==EFAULT);
  assert(_stat("file",&status)==-1 && errno==ENOSYS);
  assert(_open(NULL,0)==-1 && errno==EFAULT);
  assert(_open("file",0)==-1 && errno==ENOSYS);
  assert(_times(NULL)==(clock_t)-1 && errno==ENOSYS);
  assert(_read(1,bytes,1)==-1 && errno==EBADF);
  assert(_write(0,bytes,1)==-1 && errno==EBADF);
  assert(_read(0,bytes,-1)==-1 && errno==EINVAL);
  assert(_write(1,bytes,-1)==-1 && errno==EINVAL);
  assert(_read(0,NULL,1)==-1 && errno==EFAULT);
  assert(_write(2,NULL,1)==-1 && errno==EFAULT);
  assert(_read(0,NULL,0)==0 && _write(1,NULL,0)==0);
#ifdef TEST_IO_HOOKS
  output_budget=2;
  assert(_write(1,bytes,3)==2 && errno==EIO);
  assert(written_count==2U && written[0]=='A' && written[1]==0xFFU);
  assert(_write(2,bytes,1)==-1 && errno==EIO);
  input_budget=2; input_next=0xFE;
  assert(_read(0,bytes,3)==2 && errno==EIO);
  assert((unsigned char)bytes[0]==0xFEU && (unsigned char)bytes[1]==0xFFU);
  assert(_read(0,bytes,1)==-1 && errno==EIO);
  input_budget=3; input_next='a';
  assert(_read(0,bytes,3)==3 && bytes[2]=='c');
#else
  assert(_read(0,bytes,1)==-1 && errno==ENOSYS);
  assert(_write(1,bytes,1)==-1 && errno==ENOSYS);
  assert(_write(2,bytes,1)==-1 && errno==ENOSYS);
#endif
  /* Capture the stop before _exit's intentional infinite loop. */
  if (setjmp(exit_jump)==0) {
    exit_test_armed=1;
    CarTestExit(0);
    assert(0);
  }
  assert(exit_test_armed==0);
  puts("syscalls tests passed");
  return 0;
}
