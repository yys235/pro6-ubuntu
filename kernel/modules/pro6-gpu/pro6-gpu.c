// SPDX-License-Identifier: GPL-2.0
/*
 * PRO6 Mali GPU bring-up. LK hands Linux the GPU unpowered: the external
 * FAN53555 buck on I2C7 (0x11010000) at 0x60 is disabled, so the SPM MFG
 * MTCMOS never acks and the whole 0x13000000 region stays dead.
 *
 * Sequence (verified live on hardware, 2026-10-25):
 *   1. apply the mali@13040000 + i2c7 enable devicetree overlay
 *   2. enable the FAN53555 VGPU buck (reg0 bit7, margin kept -> ~1.12 V)
 *   3. GPU SRAM LDO on (infracfg_ao 0xfbc = 0x1ff)
 *   4. power MFG_ASYNC -> MFG -> MFG_CORE0-3 MTCMOS domains, with the
 *      full per-domain cleanup (SRAM, ISO, CLK_DIS, RST_B) once both
 *      PWR_STATUS registers ack. Cores can ack slowly right after the
 *      MFG parent comes up (LK leaves them in an illegal state the FSM
 *      clears), so poll generously and retry each core once.
 *   5. enable the mali node clocks through the clock framework
 *   6. one MFG reset pulse via the watchdog SW system reset: the GPU's
 *      internal PMU FSM ends up stuck in a perpetual power transition
 *      if it ever attempted one while the SPM domains were down (this
 *      is what panfrost's early autoload does); the pulse clears it.
 *   7. manual PMU power-on handshake: L2 (0x1A0/0x160), shader cores
 *      (0x180/0x140), tiler (0x190/0x150) -- after which panfrost's
 *      own runtime PM resume passes cleanly on every later cycle.
 */
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/module.h>
#include <linux/of.h>

#define SPM_BASE		0x10006000
#define INFRACFG_AO_BASE	0x10001000
#define TOPRGU_BASE		0x10007000
#define GPU_BASE		0x13040000

#define TOPRGU_SWSYSRST		0x0018
#define TOPRGU_KEY		0x88000000
#define MFG_RST_BIT		BIT(2)

#define SPM_PWR_STATUS		0x0180
#define SPM_PWR_STATUS_2ND	0x0184
#define SPM_MFG_ASYNC_CON	0x0334
#define SPM_MFG_CON		0x0338
#define SPM_MFG_SRAM_CON	0x033c
#define SPM_MFG_CORE0_CON	0x0340

#define PWR_RST_B_BIT		BIT(0)
#define PWR_ISO_BIT		BIT(1)
#define PWR_ON_BIT		BIT(2)
#define PWR_ON_2ND_BIT		BIT(3)
#define PWR_CLK_DIS_BIT		BIT(4)
#define CORE_SRAM_PDN_BIT	BIT(8)
#define MFG_SRAM_PDN_BITS	0x3
#define MFG_SRAM_ACK_MASK	0x30000
#define CORE_SRAM_ACK(i)	BIT(20 + (i))

#define MFG_ASYNC_STA_MASK	BIT(13)
#define MFG_STA_MASK		BIT(12)
#define CORE_STA_MASK(i)	BIT(8 + (i))

/* GPU PMU registers, panfrost_regs.h layout */
#define GPU_SHADER_PRESENT_LO	0x100
#define GPU_L2_PRESENT_LO	0x120
#define GPU_TILER_PRESENT_LO	0x110
#define SHADER_READY_LO		0x140
#define TILER_READY_LO		0x150
#define L2_READY_LO		0x160
#define SHADER_PWRON_LO		0x180
#define TILER_PWRON_LO		0x190
#define L2_PWRON_LO		0x1A0

#define FAN53555_ADDR		0x60
#define FAN53555_VSEL0		0x00
#define FAN53555_EN		0x80

extern const char gpu_dtbo[];
extern const unsigned int gpu_dtbo_len;

static int overlay_id = -1;
static void __iomem *spm;
static void __iomem *infra_ao;
static void __iomem *toprgu;
static void __iomem *gpu;
static struct clk *clk_core, *clk_bus;

static int fan53555_enable(void)
{
	struct device_node *np;
	struct i2c_adapter *adap = NULL;
	struct i2c_msg msgs[2], wmsg;
	u8 reg = FAN53555_VSEL0, rd, wr_val;
	int i, ret;

	np = of_find_node_by_path("/i2c@11010000");
	if (!np)
		return -ENODEV;

	for (i = 0; i < 150 && !adap; i++) {
		adap = of_find_i2c_adapter_by_node(np);
		if (!adap)
			msleep(100);
	}
	of_node_put(np);
	if (!adap) {
		pr_err("pro6_gpu: i2c7 adapter never appeared\n");
		return -ENXIO;
	}

	msgs[0].addr = FAN53555_ADDR; msgs[0].flags = 0;
	msgs[0].len = 1;  msgs[0].buf = &reg;
	msgs[1].addr = FAN53555_ADDR; msgs[1].flags = I2C_M_RD;
	msgs[1].len = 1;  msgs[1].buf = &rd;
	ret = i2c_transfer(adap, msgs, 2);
	if (ret != 2) {
		ret = -EIO;
		goto out;
	}
	if (rd & FAN53555_EN) {
		pr_info("pro6_gpu: FAN53555 already on (VSEL0=0x%02x)\n", rd);
		ret = 0;
		goto out;
	}
	wr_val = rd | FAN53555_EN;
	wmsg.addr = FAN53555_ADDR; wmsg.flags = 0;
	wmsg.len = 2; wmsg.buf = (u8 [2]){ FAN53555_VSEL0, wr_val };
	ret = i2c_transfer(adap, &wmsg, 1);
	if (ret != 1) {
		ret = -EIO;
		goto out;
	}
	pr_info("pro6_gpu: FAN53555 VGPU buck enabled (VSEL0 0x%02x -> 0x%02x)\n",
		rd, wr_val);
	msleep(1);
	ret = 0;
out:
	put_device(&adap->dev);
	return ret;
}

/* Power one SPM MTCMOS domain on and finish the whole cleanup sequence.
 * Waits for BOTH status registers (they can lag seconds for MFG cores
 * right after the parent domain comes up). */
static int domain_on(u32 ctl_off, u32 sta_mask)
{
	void __iomem *ctl = spm + ctl_off;
	u32 val;
	int ret, tmp;

	val = readl(ctl);
	writel(val | PWR_ON_BIT, ctl);
	writel(val | PWR_ON_BIT | PWR_ON_2ND_BIT, ctl);

	ret = readx_poll_timeout(readl, spm + SPM_PWR_STATUS, tmp,
				 tmp & sta_mask, 1000, 10000000);
	if (!ret)
		ret = readx_poll_timeout(readl, spm + SPM_PWR_STATUS_2ND, tmp,
					 tmp & sta_mask, 1000, 10000000);
	if (ret)
		return ret;

	val = readl(ctl);
	writel(val & ~PWR_CLK_DIS_BIT, ctl);
	val &= ~PWR_CLK_DIS_BIT;
	writel(val & ~PWR_ISO_BIT, ctl);
	val &= ~PWR_ISO_BIT;
	writel(val | PWR_RST_B_BIT, ctl);
	return 0;
}

static int mfg_family_on(void)
{
	void __iomem *ctl;
	u32 val, failed = 0;
	int ret, tmp, i;

	ret = domain_on(SPM_MFG_ASYNC_CON, MFG_ASYNC_STA_MASK);
	if (ret)
		return ret;

	ret = domain_on(SPM_MFG_CON, MFG_STA_MASK);
	if (ret)
		return ret;

	/* MFG SRAM up */
	val = readl(spm + SPM_MFG_SRAM_CON);
	writel(val & ~MFG_SRAM_PDN_BITS, spm + SPM_MFG_SRAM_CON);
	readx_poll_timeout(readl, spm + SPM_MFG_SRAM_CON, tmp,
			   !(tmp & MFG_SRAM_ACK_MASK), 1000, 10000000);

	/*
	 * Powering the MFG parent resets its core subdomains (LK leaves
	 * them on with the parent off, an illegal state the FSM clears).
	 * Bring all four back up: request power on ALL cores first (the
	 * SPM FSM sequences them internally and cold-boot acks are slow
	 * and uneven), then poll each core's status with a generous
	 * window, then per-core SRAM + cleanup. One full retry per core
	 * for stragglers. panfrost must NOT autoload during this window
	 * (blacklisted via modprobe.d; the service modprobes it after
	 * this module returns) -- its power transitions against a
	 * half-powered GPU wedge the PMU FSM and the SPM core acks.
	 */
	for (i = 0; i < 4; i++)
		writel(readl(spm + SPM_MFG_CORE0_CON + i * 4) |
		       PWR_ON_BIT | PWR_ON_2ND_BIT,
		       spm + SPM_MFG_CORE0_CON + i * 4);

	for (i = 0; i < 4; i++) {
		void __iomem *ctl = spm + SPM_MFG_CORE0_CON + i * 4;
		int ret2 = 0, tmp;

		if (!readx_poll_timeout(readl, spm + SPM_PWR_STATUS, tmp,
					tmp & CORE_STA_MASK(i), 1000, 30000000))
			ret2 = readx_poll_timeout(readl, spm + SPM_PWR_STATUS_2ND,
						  tmp, tmp & CORE_STA_MASK(i),
						  1000, 30000000);
		if (ret2) {
			/* full re-request cycle for stragglers */
			writel(readl(ctl) & ~(PWR_ON_BIT | PWR_ON_2ND_BIT), ctl);
			msleep(50);
			writel(readl(ctl) | PWR_ON_BIT | PWR_ON_2ND_BIT, ctl);
			if (readx_poll_timeout(readl, spm + SPM_PWR_STATUS, tmp,
					       tmp & CORE_STA_MASK(i), 1000, 30000000))
				ret2 = readx_poll_timeout(readl, spm + SPM_PWR_STATUS_2ND,
							  tmp, tmp & CORE_STA_MASK(i),
							  1000, 30000000);
		}
		if (ret2) {
			pr_warn("pro6_gpu: MFG_CORE%d power on failed\n", i);
			failed |= BIT(i);
			continue;
		}
		val = readl(ctl);
		writel(val & ~PWR_CLK_DIS_BIT, ctl);
		val &= ~PWR_CLK_DIS_BIT;
		writel(val & ~PWR_ISO_BIT, ctl);
		val &= ~PWR_ISO_BIT;
		writel(val | PWR_RST_B_BIT, ctl);
		/* per-core SRAM up */
		writel(readl(ctl) & ~CORE_SRAM_PDN_BIT, ctl);
		readx_poll_timeout(readl, spm + SPM_MFG_SRAM_CON, tmp,
				   !(tmp & CORE_SRAM_ACK(i)), 1000, 10000000);
	}
	readx_poll_timeout(readl, spm + SPM_MFG_SRAM_CON, tmp,
			   !(tmp & 0x00f00000), 1000, 10000000);
	return failed ? -EIO : 0;
}

static int gpu_clks_on(void)
{
	struct device_node *np = of_find_node_by_path("/mali@13040000");
	int ret;

	if (!np)
		return -ENODEV;
	clk_core = of_clk_get_by_name(np, "core");
	clk_bus = of_clk_get_by_name(np, "bus");
	of_node_put(np);
	if (IS_ERR(clk_core) || IS_ERR(clk_bus)) {
		pr_err("pro6_gpu: clock get failed\n");
		return -EINVAL;
	}
	ret = clk_prepare_enable(clk_core);
	if (ret)
		return ret;
	ret = clk_prepare_enable(clk_bus);
	pr_info("pro6_gpu: clocks on (core=%lu bus=%lu)\n",
		clk_get_rate(clk_core), clk_get_rate(clk_bus));
	return ret;
}

/* One MFG subsystem reset pulse via the watchdog sw system reset. Clears
 * a GPU PMU FSM left stuck mid-transition (e.g. by panfrost autoloading
 * and probing before this module could power the SPM domains). */
static void mfg_reset_pulse(void)
{
	u32 v = readl(toprgu + TOPRGU_SWSYSRST);

	writel((v & ~MFG_RST_BIT) | TOPRGU_KEY | MFG_RST_BIT,
	       toprgu + TOPRGU_SWSYSRST);
	udelay(1);
	writel((readl(toprgu + TOPRGU_SWSYSRST) & ~MFG_RST_BIT) | TOPRGU_KEY,
	       toprgu + TOPRGU_SWSYSRST);
}

/* panfrost_gpu_power_on()-style handshake with the real register offsets.
 * Done up front so the GPU is alive before any client shows up; panfrost
 * re-running it later is idempotent (READY already matches). */
static int gpu_pmu_on(void)
{
	u32 l2, sh, ti, v;
	int ret;

	l2 = readl(gpu + GPU_L2_PRESENT_LO);
	sh = readl(gpu + GPU_SHADER_PRESENT_LO);
	ti = readl(gpu + GPU_TILER_PRESENT_LO);
	pr_info("pro6_gpu: PMU present l2=0x%x shader=0x%x tiler=0x%x\n",
		l2, sh, ti);
	if (!l2 || !sh)
		return -ENODEV;

	writel(l2, gpu + L2_PWRON_LO);
	ret = readl_relaxed_poll_timeout(gpu + L2_READY_LO, v, v == l2, 10, 20000);
	if (ret) {
		pr_err("pro6_gpu: L2 power on failed (ready=0x%x)\n", v);
		return ret;
	}

	writel(sh, gpu + SHADER_PWRON_LO);
	ret = readl_relaxed_poll_timeout(gpu + SHADER_READY_LO, v, v == sh, 10, 20000);
	if (ret) {
		pr_err("pro6_gpu: shader power on failed (ready=0x%x want 0x%x)\n",
		       v, sh);
		return ret;
	}

	writel(ti, gpu + TILER_PWRON_LO);
	ret = readl_relaxed_poll_timeout(gpu + TILER_READY_LO, v, v == ti, 10, 20000);
	if (ret) {
		pr_err("pro6_gpu: tiler power on failed (ready=0x%x)\n", v);
		return ret;
	}

	pr_info("pro6_gpu: PMU ready: l2=0x%x shader=0x%x tiler=0x%x\n",
		readl(gpu + L2_READY_LO), readl(gpu + SHADER_READY_LO),
		readl(gpu + TILER_READY_LO));
	return 0;
}

static int __init pro6_gpu_init(void)
{
	int ret;

	spm = ioremap(SPM_BASE, 0x1000);
	infra_ao = ioremap(INFRACFG_AO_BASE, 0x1000);
	toprgu = ioremap(TOPRGU_BASE, 0x100);
	gpu = ioremap(GPU_BASE, 0x2000);
	if (!spm || !infra_ao || !toprgu || !gpu)
		return -ENOMEM;

	ret = of_overlay_fdt_apply(gpu_dtbo, gpu_dtbo_len, &overlay_id, NULL);
	if (ret) {
		pr_err("pro6_gpu: overlay apply failed: %d\n", ret);
		goto err;
	}

	ret = fan53555_enable();
	if (ret) {
		pr_err("pro6_gpu: FAN53555 enable failed: %d\n", ret);
		goto err;
	}

	/* GPU SRAM LDO: RG_GPULDO on */
	writel(0x1ff, infra_ao + 0xfbc);

	ret = mfg_family_on();
	if (ret) {
		pr_err("pro6_gpu: MFG MTCMOS power on failed: %d (sta=0x%08x 2nd=0x%08x)\n",
		       ret, readl(spm + SPM_PWR_STATUS),
		       readl(spm + SPM_PWR_STATUS_2ND));
		goto err;
	}

	ret = gpu_clks_on();
	if (ret) {
		pr_err("pro6_gpu: clock enable failed: %d\n", ret);
		goto err;
	}

	mfg_reset_pulse();
	msleep(10);

	ret = gpu_pmu_on();
	if (ret) {
		pr_err("pro6_gpu: PMU handshake failed: %d\n", ret);
		goto err;
	}

	pr_info("pro6_gpu: GPU alive (sta=0x%08x 2nd=0x%08x)\n",
		readl(spm + SPM_PWR_STATUS), readl(spm + SPM_PWR_STATUS_2ND));
	return 0;

err:
	if (overlay_id >= 0)
		of_overlay_remove(&overlay_id);
	iounmap(spm);
	iounmap(infra_ao);
	return ret;
}

static void __exit pro6_gpu_exit(void)
{
	if (overlay_id >= 0)
		of_overlay_remove(&overlay_id);
	if (!IS_ERR_OR_NULL(clk_bus))
		clk_disable_unprepare(clk_bus);
	if (!IS_ERR_OR_NULL(clk_core))
		clk_disable_unprepare(clk_core);
	iounmap(gpu);
	iounmap(toprgu);
	iounmap(spm);
	iounmap(infra_ao);
}

module_init(pro6_gpu_init);
module_exit(pro6_gpu_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("PRO6 Mali GPU power (buck + LDO + MTCMOS + clocks + reset + PMU) and DT overlay");