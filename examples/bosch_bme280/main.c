#include "adapter.h"

#include <string.h>

static void observe_device(const struct bme280_dev *dev)
{
    ghostchip_observe_i8("interface.result", dev->intf_rslt);
    ghostchip_observe_u16("chip_id", dev->chip_id);
    ghostchip_observe_u16("calib.dig_t1", dev->calib_data.dig_t1);
    ghostchip_observe_i16("calib.dig_t2", dev->calib_data.dig_t2);
    ghostchip_observe_u16("calib.dig_h1", dev->calib_data.dig_h1);
    ghostchip_observe_i16("calib.dig_h2", dev->calib_data.dig_h2);
    ghostchip_observe_i16("calib.dig_h4", dev->calib_data.dig_h4);
    ghostchip_observe_i16("calib.dig_h5", dev->calib_data.dig_h5);
    ghostchip_observe_i8("calib.dig_h6", dev->calib_data.dig_h6);
}

int main(int argc, char **argv)
{
    struct ghostchip_context context = { 0x76 };
    struct bme280_dev dev = { 0 };
    struct bme280_settings settings = { 0 };
    int8_t init_result;
    int8_t configure_result = 0;
    int8_t reset_result = 0;
    const char *action = (argc > 1) ? argv[1] : "init";

    dev.intf = BME280_I2C_INTF;
    dev.read = ghostchip_read;
    dev.write = ghostchip_write;
    dev.delay_us = ghostchip_delay_us;
    dev.intf_ptr = &context;

    init_result = bme280_init(&dev);
    ghostchip_observe_i8("api.init", init_result);
    observe_device(&dev);
    if ((init_result == BME280_OK) &&
        ((strcmp(action, "configure") == 0) || (strcmp(action, "reset") == 0))) {
        settings.osr_h = BME280_OVERSAMPLING_4X;
        configure_result = bme280_set_sensor_settings(BME280_SEL_OSR_HUM, &settings, &dev);
        ghostchip_observe_i8("api.configure", configure_result);
    }
    if ((configure_result == BME280_OK) && (strcmp(action, "reset") == 0)) {
        reset_result = bme280_soft_reset(&dev);
        ghostchip_observe_i8("api.reset", reset_result);
    }
    return 0;
}
