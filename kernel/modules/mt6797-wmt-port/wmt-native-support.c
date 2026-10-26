// SPDX-License-Identifier: GPL-2.0-only
/* Native Linux implementations for WMT callback and diagnostic integration. */
#include <linux/devcoredump.h>
#include <linux/device.h>
#include <linux/kernel.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/printk.h>
#include <linux/sizes.h>
#include <linux/vmalloc.h>
#include <mtk_wcn_cmb_stub.h>
#include <aee.h>

extern struct device *wmt_dev;
static DEFINE_MUTEX(wmt_callbacks_lock);
static CMB_STUB_CB wmt_callbacks;

int mtk_wcn_cmb_stub_reg(P_CMB_STUB_CB callbacks)
{
	if (!callbacks || callbacks->size != sizeof(*callbacks))
		return -EINVAL;
	mutex_lock(&wmt_callbacks_lock);
	if (wmt_callbacks.size) {
		mutex_unlock(&wmt_callbacks_lock);
		return -EBUSY;
	}
	wmt_callbacks = *callbacks;
	mutex_unlock(&wmt_callbacks_lock);
	return 0;
}

int mtk_wcn_cmb_stub_unreg(void)
{
	mutex_lock(&wmt_callbacks_lock);
	memset(&wmt_callbacks, 0, sizeof(wmt_callbacks));
	mutex_unlock(&wmt_callbacks_lock);
	return 0;
}

static int wmt_native_deep_idle(COMBO_IF interface, unsigned int enter)
{
	int ret = -ENODEV;
	if (interface != COMBO_IF_BTIF)
		return -EOPNOTSUPP;
	mutex_lock(&wmt_callbacks_lock);
	if (wmt_callbacks.deep_idle_ctrl_cb)
		ret = wmt_callbacks.deep_idle_ctrl_cb(enter);
	mutex_unlock(&wmt_callbacks_lock);
	return ret;
}

int mt_combo_plt_enter_deep_idle(COMBO_IF interface)
{
	return wmt_native_deep_idle(interface, 1);
}

int mt_combo_plt_exit_deep_idle(COMBO_IF interface)
{
	return wmt_native_deep_idle(interface, 0);
}

int mtk_wcn_wmt_chipid_query(void)
{
	return of_machine_is_compatible("mediatek,mt6797") ? 0x6797 : -ENODEV;
}

void aee_kernel_warning_api(const char *file, const int line, const int options,
			    const char *module, const char *message, ...)
{
	va_list args;
	struct va_format format;
	va_start(args, message);
	format.fmt = message;
	format.va = &args;
	pr_err("WMT warning %s:%d [%s]: %pV\n", file, line, module, &format);
	va_end(args);
	dump_stack();
}

void aee_kernel_dal_api(const char *file, const int line, const char *message)
{
	pr_err("WMT diagnostic %s:%d: %s\n", file, line, message);
}

void aed_combo_exception_api(const int *log, int log_size, const int *data,
			     int size, const char *detail, const int options)
{
	void *copy;
	pr_err("WMT firmware exception: %s (dump bytes=%d)\n", detail, size);
	if (log && log_size > 0)
		print_hex_dump(KERN_ERR, "WMT: ", DUMP_PREFIX_OFFSET, 16, 1,
			       log, min(log_size, 256), false);
	if (!wmt_dev || IS_ERR(wmt_dev) || !data || size <= 0 || size > SZ_16M)
		return;
	copy = vmalloc(size);
	if (!copy) {
		pr_err("WMT: cannot retain firmware coredump\n");
		return;
	}
	memcpy(copy, data, size);
	dev_coredumpv(wmt_dev, copy, size, GFP_KERNEL);
}

/*
 * Native EMI MPU region protection for the CONNSYS shared DRAM window.
 * Only region 18 (the 512 KiB WiFi RAM section inside the DT-reserved
 * mediatek,consys-reserve-memory range) may be changed, matching the
 * vendor WIFI firmware download path. All other regions are refused.
 */
#include <linux/arm-smccc.h>
#include <linux/io.h>

int emi_mpu_set_region_protection(unsigned long long start_addr,
				  unsigned long long end_addr, int region,
				  unsigned int access_permission)
{
	struct arm_smccc_res result;
	if (region != 18)
		return -EINVAL;
	arm_smccc_smc(0x82000209, start_addr, end_addr,
		      access_permission | ((unsigned int)region << 27),
		      0, 0, 0, 0, &result);
	return (int)result.a0;
}
EXPORT_SYMBOL(emi_mpu_set_region_protection);

/*
 * The vendor PPM sysboost policy is not ported; WiFi uses these only as
 * performance hints. Accept the calls without touching cpufreq/scheduler
 * state so the WLAN driver link stays honest about what is implemented.
 * Signatures are ABI-identical to enum ppm_sysboost_user (int-sized).
 */
void mt_ppm_sysboost_core(unsigned int user, unsigned int core_num)
{
}
EXPORT_SYMBOL(mt_ppm_sysboost_core);

void mt_ppm_sysboost_freq(unsigned int user, unsigned int freq)
{
}
EXPORT_SYMBOL(mt_ppm_sysboost_freq);

/*
 * Chip-reset request flag shared with the WLAN driver: wlan_lib sets it on
 * fatal hardware errors and the WMT/WiFi chrdev performs the recovery.
 * The vendor tree defined this in the combined module; with WMT and WLAN
 * as separate modules WMT owns it and exports it to the WLAN module.
 */
u32 g_IsNeedDoChipReset;
EXPORT_SYMBOL(g_IsNeedDoChipReset);
