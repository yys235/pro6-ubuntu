// SPDX-License-Identifier: GPL-2.0
/* pro6-mback: Synaptics RMI4 F1A (0D capacitive button) driver for the
 * Meizu PRO 6 front mBack key, which hangs off the S3718AR touch
 * controller's fn1a function (present in the PDT but unbound because
 * CONFIG_RMI4_F1A is not set in this kernel).
 *
 * On probe it dumps the F1A query/control/data registers, enables the
 * button interrupt, and reports KEY_HOME on press/release.
 */
#include <linux/input.h>
#include <linux/module.h>
#include <linux/slab.h>
#include "rmi_bus.h"
#include "rmi_driver.h"

struct mback_data {
	struct input_dev *input;
	u8 num_buttons;
};

static u8 keymap[8] = { KEY_HOME, KEY_BACK, KEY_MENU, KEY_SEARCH,
			KEY_ENTER, KEY_LEFT, KEY_RIGHT, KEY_UP };

static irqreturn_t mback_attention(int irq, void *ctx)
{
	struct rmi_function *fn = ctx;
	struct mback_data *mb = dev_get_drvdata(&fn->dev);
	u8 state = 0;
	int i, err;

	err = rmi_read_block(fn->rmi_dev, fn->fd.data_base_addr, &state, 1);
	if (err) {
		dev_err(&fn->dev, "mback: data read failed: %d\n", err);
		return IRQ_RETVAL(err);
	}
	dev_info(&fn->dev, "mback: button state 0x%02x\n", state);
	for (i = 0; i < mb->num_buttons && i < 8; i++)
		input_report_key(mb->input, keymap[i], !!(state & BIT(i)));
	input_sync(mb->input);
	return IRQ_HANDLED;
}

static int mback_probe(struct rmi_function *fn)
{
	struct mback_data *mb;
	u8 qry[2] = {0}, ctrl[2] = {0}, data0 = 0;
	int err;

	mb = devm_kzalloc(&fn->dev, sizeof(*mb), GFP_KERNEL);
	if (!mb)
		return -ENOMEM;

	err = rmi_read_block(fn->rmi_dev, fn->fd.query_base_addr, qry, 2);
	if (err) {
		dev_err(&fn->dev, "mback: query read failed: %d\n", err);
		return err;
	}
	err = rmi_read_block(fn->rmi_dev, fn->fd.control_base_addr, ctrl, 2);
	if (err)
		dev_warn(&fn->dev, "mback: control read failed: %d\n", err);
	err = rmi_read_block(fn->rmi_dev, fn->fd.data_base_addr, &data0, 1);
	if (err)
		dev_warn(&fn->dev, "mback: data read failed: %d\n", err);

	mb->num_buttons = (qry[0] & 0x7) + 1;
	dev_info(&fn->dev,
		 "mback: F1A query=0x%02x,0x%02x control=0x%02x,0x%02x data=0x%02x buttons=%d irqs=%u\n",
		 qry[0], qry[1], ctrl[0], ctrl[1], data0, mb->num_buttons,
		 fn->num_of_irqs);

	mb->input = devm_input_allocate_device(&fn->dev);
	if (!mb->input)
		return -ENOMEM;
	mb->input->name = "pro6-mback";
	mb->input->id.bustype = BUS_I2C;
	input_set_capability(mb->input, EV_KEY, KEY_HOME);
	if (mb->num_buttons > 1)
		input_set_capability(mb->input, EV_KEY, KEY_BACK);
	input_set_drvdata(mb->input, fn);

	dev_set_drvdata(&fn->dev, mb);
	err = input_register_device(mb->input);
	if (err) {
		dev_err(&fn->dev, "mback: input register failed: %d\n", err);
		return err;
	}

	/* config() only runs at first sensor enable; when this module is
	 * loaded later, enable the button interrupt from probe instead. */
	{
		u8 ctrl1 = 0;
		struct rmi_driver *drv = fn->rmi_dev->driver;

		if (!rmi_read(fn->rmi_dev, fn->fd.control_base_addr + 1,
			      &ctrl1) && !(ctrl1 & BIT(0))) {
			err = rmi_write(fn->rmi_dev,
					fn->fd.control_base_addr + 1,
					ctrl1 | BIT(0));
			dev_info(&fn->dev,
				 "mback: ctrl1 0x%02x -> enable: %d\n",
				 ctrl1, err);
		}
		if (drv->set_irq_bits)
			drv->set_irq_bits(fn->rmi_dev, fn->irq_mask);
	}
	return 0;
}

static int mback_config(struct rmi_function *fn)
{
	struct rmi_driver *drv = fn->rmi_dev->driver;
	u8 ctrl1 = 0;
	int err;

	/* F1A Control1 bit0 = button interrupt enable (vendor dsx layout) */
	err = rmi_read(fn->rmi_dev, fn->fd.control_base_addr + 1, &ctrl1);
	if (err) {
		dev_warn(&fn->dev, "mback: ctrl1 read failed: %d\n", err);
		return 0;
	}
	if (!(ctrl1 & BIT(0))) {
		err = rmi_write(fn->rmi_dev, fn->fd.control_base_addr + 1,
				ctrl1 | BIT(0));
		if (err)
			dev_warn(&fn->dev, "mback: ctrl1 write failed: %d\n",
				 err);
		else
			dev_info(&fn->dev, "mback: button interrupt enabled\n");
	}
	if (drv->set_irq_bits)
		drv->set_irq_bits(fn->rmi_dev, fn->irq_mask);
	return 0;
}

static struct rmi_function_handler mback_handler = {
	.driver = { .name = "pro6_mback" },
	.func = 0x1a,
	.probe = mback_probe,
	.config = mback_config,
	.attention = mback_attention,
};
static int __init mback_init(void)
{
	return rmi_register_function_handler(&mback_handler);
}

static void __exit mback_exit(void)
{
	rmi_unregister_function_handler(&mback_handler);
}

module_init(mback_init);
module_exit(mback_exit);
MODULE_DESCRIPTION("Meizu PRO 6 mBack key via Synaptics RMI4 F1A");
MODULE_LICENSE("GPL");
