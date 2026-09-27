#include "adapter.h"

#include <stdio.h>

static int read_status(void)
{
    int status;
    if (scanf("%d", &status) != 1) {
        return -127;
    }
    return status;
}

BME280_INTF_RET_TYPE ghostchip_read(uint8_t reg_addr, uint8_t *reg_data, uint32_t len, void *intf_ptr)
{
    struct ghostchip_context *context = (struct ghostchip_context *)intf_ptr;
    uint32_t index;
    int status;
    unsigned value;
    if ((context == NULL) || (reg_data == NULL) || (len == 0)) {
        return -127;
    }
    if (printf("R %u %u %u\n", context->address, reg_addr, (unsigned)len) < 0 || fflush(stdout)) {
        return -127;
    }
    status = read_status();
    if (status != 0) {
        return (BME280_INTF_RET_TYPE)status;
    }
    for (index = 0; index < len; ++index) {
        if ((scanf("%u", &value) != 1) || (value > 255)) {
            return -127;
        }
        reg_data[index] = (uint8_t)value;
    }
    return BME280_INTF_RET_SUCCESS;
}

BME280_INTF_RET_TYPE ghostchip_write(uint8_t reg_addr, const uint8_t *reg_data, uint32_t len, void *intf_ptr)
{
    struct ghostchip_context *context = (struct ghostchip_context *)intf_ptr;
    uint32_t index;
    if ((context == NULL) || (reg_data == NULL) || (len == 0)) {
        return -127;
    }
    if (printf("W %u %u %u", context->address, reg_addr, (unsigned)len) < 0) {
        return -127;
    }
    for (index = 0; index < len; ++index) {
        if (printf(" %u", reg_data[index]) < 0) {
            return -127;
        }
    }
    if (printf("\n") < 0 || fflush(stdout)) {
        return -127;
    }
    return (BME280_INTF_RET_TYPE)read_status();
}

void ghostchip_delay_us(uint32_t period, void *intf_ptr)
{
    struct ghostchip_context *context = (struct ghostchip_context *)intf_ptr;
    (void)context;
    if (printf("D %u\n", (unsigned)period) < 0 || fflush(stdout)) {
        return;
    }
    (void)read_status();
}

void ghostchip_observe_i8(const char *name, int value)
{
    (void)printf("O %s i8 %d\n", name, value);
    (void)fflush(stdout);
}

void ghostchip_observe_u16(const char *name, unsigned value)
{
    (void)printf("O %s u16 %u\n", name, value);
    (void)fflush(stdout);
}

void ghostchip_observe_i16(const char *name, int value)
{
    (void)printf("O %s i16 %d\n", name, value);
    (void)fflush(stdout);
}
