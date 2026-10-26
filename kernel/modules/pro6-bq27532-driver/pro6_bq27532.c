// SPDX-License-Identifier: GPL-2.0-only
/* Native, read-only BQ27532 measurements for the Meizu PRO 6.
 * Register definitions verified against meizuosc/m685 BQ27532 sources
 * and this phone's original hardware I2C0/0x55 registration.
 * No reset, unseal, data-flash, calibration or charger programming.
 */
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/power_supply.h>
#include <linux/workqueue.h>

struct pro6_gauge {
	struct i2c_client *client;
	struct power_supply *battery;
	struct delayed_work poll;
};

static enum power_supply_property pro6_properties[] = {
	POWER_SUPPLY_PROP_STATUS, POWER_SUPPLY_PROP_PRESENT,
	POWER_SUPPLY_PROP_VOLTAGE_NOW, POWER_SUPPLY_PROP_CURRENT_NOW,
	POWER_SUPPLY_PROP_CAPACITY, POWER_SUPPLY_PROP_TEMP,
	POWER_SUPPLY_PROP_CHARGE_NOW, POWER_SUPPLY_PROP_CHARGE_FULL,
};

static int pro6_get_property(struct power_supply *psy,
			     enum power_supply_property property,
			     union power_supply_propval *value)
{
	struct pro6_gauge *gauge = power_supply_get_drvdata(psy);
	int reg, raw;

	switch (property) {
	case POWER_SUPPLY_PROP_STATUS:
		raw = i2c_smbus_read_word_data(gauge->client, 0x0a);
		if (raw < 0)
			return raw;
		if (raw & BIT(9)) {
			value->intval = POWER_SUPPLY_STATUS_FULL;
			return 0;
		}
		raw = i2c_smbus_read_word_data(gauge->client, 0x14);
		if (raw < 0)
			return raw;
		raw = (s16)raw;
		value->intval = raw > 5 ? POWER_SUPPLY_STATUS_CHARGING :
			(raw < -5 ? POWER_SUPPLY_STATUS_DISCHARGING :
			 POWER_SUPPLY_STATUS_NOT_CHARGING);
		return 0;
	case POWER_SUPPLY_PROP_PRESENT:
	case POWER_SUPPLY_PROP_VOLTAGE_NOW: reg = 0x08; break;
	case POWER_SUPPLY_PROP_CURRENT_NOW: reg = 0x14; break;
	case POWER_SUPPLY_PROP_CAPACITY: reg = 0x20; break;
	case POWER_SUPPLY_PROP_TEMP: reg = 0x06; break;
	case POWER_SUPPLY_PROP_CHARGE_NOW: reg = 0x10; break;
	case POWER_SUPPLY_PROP_CHARGE_FULL: reg = 0x12; break;
	default: return -EINVAL;
	}
	raw = i2c_smbus_read_word_data(gauge->client, reg);
	if (raw < 0)
		return raw;
	switch (property) {
	case POWER_SUPPLY_PROP_PRESENT: value->intval = raw > 2000; break;
	case POWER_SUPPLY_PROP_CURRENT_NOW: value->intval = (s16)raw * 1000; break;
	case POWER_SUPPLY_PROP_VOLTAGE_NOW:
	case POWER_SUPPLY_PROP_CHARGE_NOW:
	case POWER_SUPPLY_PROP_CHARGE_FULL: value->intval = raw * 1000; break;
	case POWER_SUPPLY_PROP_TEMP: value->intval = raw - 2731; break;
	case POWER_SUPPLY_PROP_CAPACITY:
		if (raw > 100)
			return -ENODATA;
		value->intval = raw;
		break;
	default: return -EINVAL;
	}
	return 0;
}

static const struct power_supply_desc pro6_battery_desc = {
	.name = "pro6-battery",
	.type = POWER_SUPPLY_TYPE_BATTERY,
	.properties = pro6_properties,
	.num_properties = ARRAY_SIZE(pro6_properties),
	.get_property = pro6_get_property,
};

static void pro6_poll(struct work_struct *work)
{
	struct pro6_gauge *gauge = container_of(to_delayed_work(work),
					       struct pro6_gauge, poll);
	power_supply_changed(gauge->battery);
	schedule_delayed_work(&gauge->poll, 20 * HZ);
}

static void pro6_stop_poll(void *data)
{
	struct pro6_gauge *gauge = data;
	cancel_delayed_work_sync(&gauge->poll);
}

static int pro6_probe(struct i2c_client *client)
{
	struct power_supply_config config = {};
	struct pro6_gauge *gauge;
	int voltage, capacity;

	voltage = i2c_smbus_read_word_data(client, 0x08);
	capacity = i2c_smbus_read_word_data(client, 0x20);
	if (voltage < 2500 || voltage > 4500 || capacity < 0 || capacity > 100)
		return dev_err_probe(&client->dev, -ENODEV, "invalid gauge measurements\n");
	gauge = devm_kzalloc(&client->dev, sizeof(*gauge), GFP_KERNEL);
	if (!gauge)
		return -ENOMEM;
	gauge->client = client;
	config.drv_data = gauge;
	gauge->battery = devm_power_supply_register(&client->dev, &pro6_battery_desc, &config);
	if (IS_ERR(gauge->battery))
		return PTR_ERR(gauge->battery);
	INIT_DELAYED_WORK(&gauge->poll, pro6_poll);
	schedule_delayed_work(&gauge->poll, 20 * HZ);
	return devm_add_action_or_reset(&client->dev, pro6_stop_poll, gauge);
}

static const struct i2c_device_id pro6_ids[] = {
	{ "pro6-bq27532", 0 }, { }
};
MODULE_DEVICE_TABLE(i2c, pro6_ids);

static struct i2c_driver pro6_driver = {
	.driver.name = "pro6-bq27532",
	.probe = pro6_probe,
	.id_table = pro6_ids,
};
module_i2c_driver(pro6_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Meizu PRO 6 read-only BQ27532 battery measurements");
