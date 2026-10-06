#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>

static uint8_t heap[64];
#define SBRK_HEAP_START ((uintptr_t)heap)
#define SBRK_HEAP_LIMIT ((uintptr_t)heap + sizeof(heap))
#include "../Core/Src/sysmem.c"

int main(void) {
  assert(_sbrk(0)==heap);
  assert(_sbrk(-1)==(void *)-1 && errno==ENOMEM);
  assert(_sbrk(0)==heap);
  assert(_sbrk(32)==heap);
  assert(_sbrk(33)==(void *)-1 && errno==ENOMEM);
  assert(_sbrk(0)==heap+32);
  assert(_sbrk(32)==heap+32);
  assert(_sbrk(1)==(void *)-1 && errno==ENOMEM);
  assert(_sbrk(-64)==heap+64);
  assert(_sbrk(0)==heap);
  assert(_sbrk(PTRDIFF_MIN)==(void *)-1 && errno==ENOMEM);
  assert(_sbrk(PTRDIFF_MAX)==(void *)-1 && errno==ENOMEM);
  assert(_sbrk(0)==heap);
  assert(_sbrk(16)==heap);
  assert(_sbrk(-17)==(void *)-1 && errno==ENOMEM);
  assert(_sbrk(0)==heap+16);
  assert(_sbrk(-16)==heap+16 && _sbrk(0)==heap);
  puts("sysmem tests passed");
  return 0;
}
