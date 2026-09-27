#include "gc_hal.h"
#include <stdint.h>

enum { ADXL345_ADDRESS = 0x53, INT_SOURCE = 0x30, FIFO_CTL = 0x38 };
static volatile uint8_t diagnostic_interrupt_snapshot;

int main(void) {
    uint8_t source;
    uint8_t bypass = 0;

    /* Bug: the diagnostic read consumes latched non-data interrupts. */
    if (gc_i2c_read(ADXL345_ADDRESS, INT_SOURCE, &source, 1)) return 10;
    diagnostic_interrupt_snapshot = source;
    if (gc_i2c_read(ADXL345_ADDRESS, INT_SOURCE, &source, 1)) return 11;
    if (gc_i2c_write(ADXL345_ADDRESS, FIFO_CTL, &bypass, 1)) return 12;
    return (source & 0x40u) ? 0 : 2;
}
