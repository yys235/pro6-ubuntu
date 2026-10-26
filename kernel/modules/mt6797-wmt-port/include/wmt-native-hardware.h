/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef PRO6_WMT_NATIVE_HARDWARE_H
#define PRO6_WMT_NATIVE_HARDWARE_H
#include <linux/types.h>
int wmt_native_pmic_update(u16 reg, u32 mask, u32 value);
int wmt_native_emi_set(u64 start, u64 end, int region, u32 permission);
int wmt_native_reset(int mask, int assert);
phys_addr_t wmt_native_emi_base(void);
void wmt_native_release_resources(void);
int wmt_native_validate_platform(void);
struct platform_device;
int wmt_native_power_prepare(struct platform_device *device);
int wmt_native_power(bool on);
void wmt_native_power_release(void);
#define WMT_SET_POWER(on) do { \
	int _ret = wmt_native_power(on); \
	if (_ret) return _ret; \
} while (0)
#define WMT_REGULATOR_CALL(call) do { \
	int _ret = (call); \
	if (_ret) return _ret; \
} while (0)
#define WMT_SET_PMIC(flag, value) do { \
	int _ret = wmt_native_pmic_update(flag##_ADDR, \
		flag##_MASK << flag##_SHIFT, (value) << flag##_SHIFT); \
	if (_ret) return _ret; \
} while (0)
#define WMT_SET_EMI(...) do { \
	int _ret = wmt_native_emi_set(__VA_ARGS__); \
	if (_ret) return _ret; \
} while (0)
#define WMT_SET_RESET(mask, assert) do { \
	int _ret = wmt_native_reset(mask, assert); \
	if (_ret) return _ret; \
} while (0)
#endif
