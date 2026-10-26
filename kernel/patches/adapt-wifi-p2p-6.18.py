"""Translate legacy P2P cfg80211 signatures without ABI casts."""
from pathlib import Path
import re

root = Path('/root/pro6-linux/mt6797-wifi-port')
names = ['add_iface', 'change_iface', 'change_beacon', 'stop_ap',
         'set_wiphy_params', 'del_station', 'set_bitrate_mask',
         'add_key', 'get_key', 'del_key', 'set_default_key',
         'set_txpower', 'get_txpower']

def migrate(s, name):
    marker = 'mtk_p2p_cfg80211_' + name + '('
    pos = 0
    while (start := s.find(marker, pos)) >= 0:
        left = start + len(marker)
        right, depth = left, 1
        while depth:
            if s[right] == '(': depth += 1
            if s[right] == ')': depth -= 1
            right += 1
        tail = s[right:].lstrip()
        # Never rewrite call sites or comments.
        if not tail.startswith((';', '{')):
            pos = right
            continue
        params = s[left:right - 1]
        guard = ''
        if name == 'add_iface':
            params = params.replace('const char *name,', 'const char *name, unsigned char name_assign_type,')
            params = re.sub(r'\bu32 \*flags,\s*', '', params)
        elif name == 'change_iface':
            params = re.sub(r'\b(?:IN\s+)?u32 \*flags,\s*', '', params)
        elif name == 'change_beacon':
            params = params.replace('struct cfg80211_beacon_data *info', 'struct cfg80211_ap_update *update')
            guard = '\n\tstruct cfg80211_beacon_data *info = &update->beacon;'
        elif name == 'stop_ap':
            params += ', unsigned int link_id'
            guard = '\n\tif (link_id) return -EOPNOTSUPP;'
        elif name == 'set_wiphy_params':
            params = params.replace('u32 changed', 'int radio_idx, u32 changed')
            guard = '\n\tif (radio_idx > 0) return -EOPNOTSUPP;'
        elif name == 'del_station':
            params = params.replace('const u8 *mac', 'struct station_del_parameters *params')
            guard = '\n\tconst u8 *mac = params->mac;'
        elif name == 'set_bitrate_mask':
            params = params.replace('IN const u8 *peer', 'unsigned int link_id, IN const u8 *peer')
            guard = '\n\tif (link_id) return -EOPNOTSUPP;'
        elif name in ['add_key', 'get_key', 'del_key', 'set_default_key']:
            params = re.sub(r'(struct net_device \*\w+),', r'\1, int link_id,', params)
            guard = '\n\tif (link_id > 0) return -EOPNOTSUPP;'
        elif name == 'set_txpower':
            params = params.replace('enum nl80211_tx_power_setting', 'int radio_idx, enum nl80211_tx_power_setting')
            guard = '\n\tif (radio_idx > 0) return -EOPNOTSUPP;'
        elif name == 'get_txpower':
            params = params.replace('int *dbm', 'int radio_idx, unsigned int link_id, int *dbm')
            guard = '\n\tif (radio_idx > 0 || link_id) return -EOPNOTSUPP;'
        s = s[:left] + params + s[right - 1:]
        pos = left + len(params) + 1
        if tail.startswith('{') and guard:
            body = s.index('{', pos)
            s = s[:body + 1] + guard + s[body + 1:]
            pos = body + 1 + len(guard)
    return s

for path in [root / 'os/linux/gl_p2p_cfg80211.c', *root.glob('**/*.h')]:
    source = path.read_text()
    for name in names:
        source = migrate(source, name)
    if path.name == 'gl_p2p_cfg80211.c':
        source += '''
void pro6_p2p_update_mgmt_regs(struct wiphy *wiphy, struct wireless_dev *wdev,
                             struct mgmt_frame_regs *regs)
{
    u32 mask = regs->global_stypes | regs->interface_stypes;
    mtk_p2p_cfg80211_mgmt_frame_register(wiphy, wdev, MAC_FRAME_PROBE_REQ,
        !!(mask & BIT(IEEE80211_STYPE_PROBE_REQ >> 4)));
    mtk_p2p_cfg80211_mgmt_frame_register(wiphy, wdev, MAC_FRAME_ACTION,
        !!(mask & BIT(IEEE80211_STYPE_ACTION >> 4)));
}
'''
    path.write_text(source)
path = root / 'os/linux/gl_p2p.c'
source = path.read_text().replace('static struct cfg80211_ops mtk_p2p_ops = {',
    'void pro6_p2p_update_mgmt_regs(struct wiphy *, struct wireless_dev *, struct mgmt_frame_regs *);\n'
    'static struct cfg80211_ops mtk_p2p_ops = {')
source = source.replace('.mgmt_frame_register = mtk_p2p_cfg80211_mgmt_frame_register,',
                        '.update_mgmt_frame_registrations = pro6_p2p_update_mgmt_regs,')
path.write_text(source)

# platform_driver.remove is now void. Resource release remains unchanged.
path = root / 'os/linux/hif/ahb_sdioLike/ahb.c'
source = path.read_text()
source = source.replace('static int __exit HifAhbPltmRemove', 'static void __exit HifAhbPltmRemove')
match = re.search(r'static void __exit HifAhbPltmRemove\([^;]+?\)\s*\{', source)
assert match
body = match.end()
end, depth = body, 1
while depth:
    if source[end] == '{': depth += 1
    if source[end] == '}': depth -= 1
    end += 1
source = source[:body] + source[body:end].replace('return 0;', 'return;') + source[end:]
path.write_text(source)
