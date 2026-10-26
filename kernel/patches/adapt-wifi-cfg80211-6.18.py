"""Migrate callbacks without casting incompatible cfg80211 function pointers."""
from pathlib import Path
import re

root = Path('/root/pro6-linux/mt6797-wifi-port')
for relative in ['os/linux/include/gl_cfg80211.h', 'os/linux/gl_cfg80211.c']:
    path = root / relative
    source = path.read_text()
    source = source.replace('u32 *flags, struct vif_params *params', 'struct vif_params *params')
    if relative.endswith('.c'):
        source = source.replace('(UINT_16) (request->interval)',
                                '(UINT_16) (request->scan_plans[0].interval * 1000U)')
        signature = 'mtk_cfg80211_sched_scan_start('
        start = source.index(signature)
        body = source.index('{', start)
        source = source[:body + 1] + '''
    if (request->n_scan_plans != 1 || !request->scan_plans[0].interval ||
        request->scan_plans[0].interval > U16_MAX / 1000U)
        return -EINVAL;
''' + source[body + 1:]
    pattern = r'(mtk_cfg80211_(?:add_key|get_key|del_key|set_default_key)\s*\([^)]*?struct net_device \*\w+)\s*,'
    source, count = re.subn(pattern, r'\1, int link_id,', source)
    assert count == 4, (relative, count)
    pattern = r'(mtk_cfg80211_(?:add_key|get_key|del_key|set_default_key)\s*\([^;{}]*?\)\n\{)'
    source = re.sub(pattern, r'\1\n\tif (link_id > 0) return -EOPNOTSUPP;', source)
    source = source.replace('mtk_cfg80211_sched_scan_stop(IN struct wiphy *wiphy, IN struct net_device *ndev)',
                            'mtk_cfg80211_sched_scan_stop(IN struct wiphy *wiphy, IN struct net_device *ndev, u64 reqid)')
    source = source.replace('mtk_cfg80211_del_station(struct wiphy *wiphy, struct net_device *ndev, const u8 *mac)',
                            'mtk_cfg80211_del_station(struct wiphy *wiphy, struct net_device *ndev, struct station_del_parameters *params)')
    source = source.replace('struct station_del_parameters *params)\n{',
                            'struct station_del_parameters *params)\n{\n\tconst u8 *mac = params->mac;')
    source = re.sub(r'(mtk_cfg80211_tdls_mgmt\([^;{}]*?const u8 \*peer),', r'\1, int link_id,', source)
    if relative.endswith('.h'):
        source += '''
void mtk_cfg80211_update_mgmt_regs(struct wiphy *, struct wireless_dev *, struct mgmt_frame_regs *);
'''
    else:
        source += '''
void mtk_cfg80211_update_mgmt_regs(struct wiphy *wiphy, struct wireless_dev *wdev,
                                  struct mgmt_frame_regs *registers)
{
    u32 mask = registers->global_stypes | registers->interface_stypes;
    mtk_cfg80211_mgmt_frame_register(wiphy, wdev, MAC_FRAME_PROBE_REQ,
                                    !!(mask & BIT(IEEE80211_STYPE_PROBE_REQ >> 4)));
    mtk_cfg80211_mgmt_frame_register(wiphy, wdev, MAC_FRAME_ACTION,
                                    !!(mask & BIT(IEEE80211_STYPE_ACTION >> 4)));
}
'''
    path.write_text(source)

path = root / 'os/linux/gl_init.c'
source = path.read_text()
source = source.replace('.mgmt_frame_register = mtk_cfg80211_mgmt_frame_register,',
                        '.update_mgmt_frame_registrations = mtk_cfg80211_update_mgmt_regs,')
source = source.replace('void *accel_priv, select_queue_fallback_t fallback', 'struct net_device *sb_dev')
source = source.replace('WIPHY_FLAG_SUPPORTS_SCHED_SCAN', '0')
source = source.replace('prWiphy->signal_type = CFG80211_SIGNAL_TYPE_MBM;',
    'prWiphy->signal_type = CFG80211_SIGNAL_TYPE_MBM;\n'
    '\tprWiphy->max_sched_scan_reqs = 1;\n\tprWiphy->max_sched_scan_plans = 1;\n'
    '\tprWiphy->max_sched_scan_plan_interval = U16_MAX / 1000U;')
source = re.sub(r'^MODULE_SUPPORTED_DEVICE\([^\n]+\);\n', '', source, flags=re.M)
path.write_text(source)

# Leave one byte for the terminator and avoid count+1 wraparound.  The vendor
# code copied a full buffer for oversized requests, then wrote past its end.
path = root / 'os/linux/gl_proc.c'
source = path.read_text()
source, count = re.subn(r'if \(u4CopySize >= count\s*\+\s*1\)\s*\n\s*u4CopySize = count;',
                      'u4CopySize = min_t(size_t, count, sizeof(aucProcBuf) - 1);', source)
assert count >= 2, count
source = source.replace('"%s %d", aucModule, &u4Enabled',
                        '"%4s %d", aucModule, &u4Enabled')
path.write_text(source)

# Private WEXT ioctls are only part of the upstream handler structure when
# enabled in the kernel. cfg80211/nl80211 remains the standard control path.
path = root / 'os/linux/gl_wext.c'
source = path.read_text()
for member in ['num_private', 'num_private_args', 'private', 'private_args']:
    source = re.sub(rf'^(\s*\.{member}\s*=[^\n]+)', r'#ifdef CONFIG_WEXT_PRIV\n\1\n#endif', source, flags=re.M)
path.write_text(source)
