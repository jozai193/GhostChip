#ifndef GC_HAL_H
#define GC_HAL_H
#include <stddef.h>
#include <stdint.h>
int gc_i2c_write(uint8_t address, uint8_t reg, const uint8_t *data, size_t len);
int gc_i2c_read(uint8_t address, uint8_t reg, uint8_t *data, size_t len);
#endif
