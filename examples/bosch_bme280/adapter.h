#ifndef GHOSTCHIP_BOSCH_BME280_ADAPTER_H
#define GHOSTCHIP_BOSCH_BME280_ADAPTER_H

#include "bme280.h"

struct ghostchip_context {
    uint8_t address;
};

BME280_INTF_RET_TYPE ghostchip_read(uint8_t reg_addr, uint8_t *reg_data, uint32_t len, void *intf_ptr);
BME280_INTF_RET_TYPE ghostchip_write(uint8_t reg_addr, const uint8_t *reg_data, uint32_t len, void *intf_ptr);
void ghostchip_delay_us(uint32_t period, void *intf_ptr);
void ghostchip_observe_i8(const char *name, int value);
void ghostchip_observe_i16(const char *name, int value);
void ghostchip_observe_u16(const char *name, unsigned value);

#endif
