#include "gc_hal.h"
#include <stdio.h>

/* A synchronous RPC: the driver cannot continue until the model responds. */
static int exchange(char op, uint8_t address, uint8_t reg, unsigned value, unsigned *out) {
    int status;
    if (printf("%c %u %u %u\n", op, address, reg, value) < 0 || fflush(stdout)) return -1;
    if (scanf("%d %u", &status, out) != 2) return -1;
    return status;
}
int gc_i2c_write(uint8_t address, uint8_t reg, const uint8_t *data, size_t len) {
    unsigned ignored;
    if (!data || len != 1) return -1;
    return exchange('W', address, reg, data[0], &ignored);
}
int gc_i2c_read(uint8_t address, uint8_t reg, uint8_t *data, size_t len) {
    unsigned out;
    if (!data || len != 1) return -1;
    int status = exchange('R', address, reg, 0, &out);
    if (status || out > 255) return -1;
    *data = (uint8_t)out;
    return 0;
}
