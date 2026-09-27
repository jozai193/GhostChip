#include "gc_hal.h"

/* Same request and return contract; only the two writes change order. */
static int configure_humidity_x4(void) {
    uint8_t id, humidity = 3, measurement = 0;
    if (gc_i2c_read(0x76, 0xD0, &id, 1) || id != 0x60) return -1;
    if (gc_i2c_write(0x76, 0xF2, &humidity, 1)) return -1;
    if (gc_i2c_write(0x76, 0xF4, &measurement, 1)) return -1;
    if (gc_i2c_read(0x76, 0xF2, &humidity, 1) || humidity != 3) return -1;
    return 0;
}
int main(void) { return configure_humidity_x4() == 0 ? 0 : 1; }
