/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef PRO6_WMT_CONN_SEQUENCE_H
#define PRO6_WMT_CONN_SEQUENCE_H
enum { WMT_CONN_SPM, WMT_CONN_INFRA };
struct wmt_conn_io {
    void *context;
    int (*write)(void *, int, unsigned int, unsigned int);
    int (*update)(void *, int, unsigned int, unsigned int, unsigned int);
    int (*poll)(void *, int, unsigned int, unsigned int, unsigned int);
};
static inline int wmt_conn_set_power(struct wmt_conn_io *io, bool on)
{
    /* meizuosc/m685 drivers/clk/mediatek/clk-mt6797-pg.c,
     * spm_mtcmos_ctrl_conn: CCF path, not legacy mt_spm_mtcmos.c.
     * Every poll is delegated to a bounded native poll operation.
     */
    const unsigned int reset = 1U, iso = 2U, power = 4U;
    const unsigned int power2 = 8U, clock_disable = 16U;
    const unsigned int protect = (1U << 17) | (1U << 18);
    int ret;
#define WMT_CONN_STEP(call) do { ret = (call); if (ret) return ret; } while (0)
#define WMT_CONN_UPDATE(space, offset, mask, value) \
    WMT_CONN_STEP(io->update(io->context, space, offset, mask, value))
#define WMT_CONN_POLL(space, offset, mask, value) \
    WMT_CONN_STEP(io->poll(io->context, space, offset, mask, value))
    WMT_CONN_STEP(io->write(io->context, WMT_CONN_SPM, 0, 0x0b160001));
    if (on) {
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, power, power);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, power2, power2);
        WMT_CONN_POLL(WMT_CONN_SPM, 0x180, 2U, 2U);
        WMT_CONN_POLL(WMT_CONN_SPM, 0x184, 2U, 2U);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, clock_disable, 0);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, iso, 0);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, reset, reset);
        WMT_CONN_UPDATE(WMT_CONN_INFRA, 0x220, protect, 0);
        WMT_CONN_POLL(WMT_CONN_INFRA, 0x228, protect, 0);
    } else {
        WMT_CONN_UPDATE(WMT_CONN_INFRA, 0x220, protect, protect);
        WMT_CONN_POLL(WMT_CONN_INFRA, 0x228, protect, protect);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, iso, iso);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, clock_disable, clock_disable);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, reset, 0);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, power, 0);
        WMT_CONN_UPDATE(WMT_CONN_SPM, 0x32c, power2, 0);
        WMT_CONN_POLL(WMT_CONN_SPM, 0x180, 2U, 0);
        WMT_CONN_POLL(WMT_CONN_SPM, 0x184, 2U, 0);
    }
#undef WMT_CONN_POLL
#undef WMT_CONN_UPDATE
#undef WMT_CONN_STEP
    return 0;
}
#endif
