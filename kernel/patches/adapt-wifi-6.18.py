"""Incremental, source-preserving gen3 Wi-Fi migration to native Linux APIs."""
from pathlib import Path
import re

root = Path('/root/pro6-linux/mt6797-wifi-port')
for path in list(root.rglob('*.c')) + list(root.rglob('*.h')):
    source = path.read_text(errors='strict')
    # Private enum names now collide with upstream ACPI names via fb/i2c.h.
    source = re.sub(r'\bACPI_STATE_(D[0-3])\b', r'WLAN_ACPI_STATE_\1', source)
    source = source.replace('#include <linux/ftrace_event.h>', '#include <linux/trace_events.h>')
    source = source.replace('#include <stddef.h>', '#include <linux/stddef.h>')
    source = source.replace('ioremap_nocache(', 'ioremap(')
    source = source.replace('sched_clock()', 'ktime_get_mono_fast_ns()')
    source = source.replace('IEEE80211_BAND_', 'NL80211_BAND_')
    source = source.replace('STATION_INFO_ASSOC_REQ_IES', '0')
    source = re.sub(r'\bSTATION_INFO_(\w+)', r'BIT_ULL(NL80211_STA_INFO_\1)', source)
    for field in ['supported_rates', 'supported_rates_len', 'ht_capa', 'vht_capa']:
        source = source.replace(f'params->{field}', f'params->link_sta_params.{field}')
    source = re.sub(r'nla_parse_nested\((.*?)\);',
                    r'nla_parse_nested_deprecated(\1, NULL);', source, flags=re.S)
    source = re.sub(r'cfg80211_vendor_event_alloc\((\w+),',
                    r'cfg80211_vendor_event_alloc(\1, NULL,', source)
    source = source.replace('strnicmp(', 'strncasecmp(')
    source = source.replace('void *accel_priv, select_queue_fallback_t fallback',
                            'struct net_device *sb_dev')
    source = source.replace('netif_rx_ni(', 'netif_rx(')
    source = source.replace('del_timer_sync(', 'timer_delete_sync(')
    source = source.replace('struct timespec ', 'struct timespec64 ')
    source = source.replace('get_monotonic_boottime(', 'ktime_get_boottime_ts64(')
    source = re.sub(r'access_ok\(VERIFY_(?:READ|WRITE),\s*', 'access_ok(', source)
    source = re.sub(r'show_stack\(([^,]+),\s*NULL\)', r'wlan_show_task_stack(\1)', source)
    source = source.replace('kalTimeoutHandler(unsigned long arg)',
                            'kalTimeoutHandler(struct timer_list *timer)')
    source = source.replace('cfg80211_scan_done(', 'wlan_scan_done(')
    source = source.replace('cfg80211_get_bss(', 'wlan_get_bss(')
    source = source.replace('cfg80211_roamed_bss(', 'wlan_roamed_bss(')
    for api in ['results', 'stopped']:
        source = source.replace(f'cfg80211_sched_scan_{api}(priv_to_wiphy(prGlueInfo))',
            f'cfg80211_sched_scan_{api}(priv_to_wiphy(prGlueInfo), prGlueInfo->pro6_sched_reqid)')
    source = source.replace('prGlueInfo->prSchedScanRequest = request;',
        'prGlueInfo->pro6_sched_reqid = request->reqid;\n\tprGlueInfo->prSchedScanRequest = request;')
    path.write_text(source)

path = root / 'os/linux/include/gl_kal.h'
source = path.read_text()
pattern = r'#if CONFIG_ANDROID\s*/\* Defined in Android kernel source \*/\ntypedef struct wake_lock.*?#endif'
source, count = re.subn(pattern, '''#include <linux/pm_wakeup.h>
#include <linux/timekeeping.h>
typedef struct { struct wakeup_source *source; } KAL_WAKE_LOCK_T, *P_KAL_WAKE_LOCK_T;
static inline bool wlan_wakeup_active(struct wakeup_source *source)
{
    unsigned long flags;
    bool active;
    if (!source) return false;
    spin_lock_irqsave(&source->lock, flags);
    active = source->active;
    spin_unlock_irqrestore(&source->lock, flags);
    return active;
}''',
                        source, count=1, flags=re.S)
assert count == 1
start = source.index('#if CONFIG_ANDROID', source.index('/* Macros of wake_lock operations'))
end = source.index('#endif', start) + len('#endif')
source = source[:start] + '''#define KAL_WAKE_LOCK_INIT(adapter, lock, name) do { \\
    (lock)->source = wakeup_source_register(NULL, name); \\
    WARN_ON(!(lock)->source); \\
} while (0)
#define KAL_WAKE_LOCK_DESTROY(adapter, lock) do { \\
    wakeup_source_unregister((lock)->source); (lock)->source = NULL; \\
} while (0)
#define KAL_WAKE_LOCK(adapter, lock) __pm_stay_awake((lock)->source)
#define KAL_WAKE_LOCK_TIMEOUT(adapter, lock, ticks) \\
    __pm_wakeup_event((lock)->source, jiffies_to_msecs(ticks))
#define KAL_WAKE_UNLOCK(adapter, lock) __pm_relax((lock)->source)
#define KAL_WAKE_LOCK_ACTIVE(adapter, lock) \\
    wlan_wakeup_active((lock)->source)
''' + source[end:]
path.write_text(source)

path = root / 'os/linux/platform.c'
source = path.read_text()
source = source.replace('/data/nvram/APCFG/APRDEB/WIFI', '/var/lib/pro6/WIFI')
for name, flags, operation in [('nvram_read', 'O_RDONLY', 'kernel_read'),
                              ('nvram_write', 'O_WRONLY', 'kernel_write')]:
    body = f'''    struct file *file;
    loff_t position = offset;
    ssize_t result;
    if (offset < 0 || len < 0) return -EINVAL;
    file = filp_open(filename, {flags}, 0);
    if (IS_ERR(file)) return PTR_ERR(file);
    result = {operation}(file, buf, len, &position);
    filp_close(file, NULL);
    return result;'''
    pattern = rf'(^static int {name}\([^\n]+\)\n)\{{.*?^\}}'
    source, count = re.subn(pattern, lambda match: match[1] + '{\n' + body + '\n}',
                            source, flags=re.M | re.S)
    assert count == 1, name
path.write_text(source)

path = root / 'os/linux/gl_proc.c'
source = path.read_text()
pattern = r'(?:const )?struct file_operations (\w+) = \{(.*?)\n\};'
def proc_operations(match):
    body = re.sub(r'^\s*\.owner\s*=[^\n]+', '', match[2], flags=re.M)
    for field in ['open', 'read', 'write', 'llseek', 'release']:
        body = body.replace('.' + field, '.proc_' + ('lseek' if field == 'llseek' else field))
    return 'const struct proc_ops ' + match[1] + ' = {' + body + '\n};'
source, count = re.subn(pattern, proc_operations, source, flags=re.S)
assert count >= 3, count
path.write_text(source)

path = root / 'os/linux/include/gl_os.h'
source = path.read_text()
source = source.replace('#include <linux/fb.h>', '''#include <linux/fb.h>
#include <linux/stacktrace.h>
#include <net/if_inet6.h>
#include <net/addrconf.h>
static inline void wlan_scan_done(struct cfg80211_scan_request *request, bool aborted)
{
    struct cfg80211_scan_info info = { .aborted = aborted };
    cfg80211_scan_done(request, &info);
}
static inline struct cfg80211_bss *wlan_get_bss(struct wiphy *wiphy,
    struct ieee80211_channel *channel, const u8 *bssid, const u8 *ssid,
    size_t ssid_length, u16 mask, u16 capability)
{
    enum ieee80211_bss_type type = IEEE80211_BSS_TYPE_ANY;
    enum ieee80211_privacy privacy = IEEE80211_PRIVACY_ANY;
    if ((mask & capability) & WLAN_CAPABILITY_ESS) type = IEEE80211_BSS_TYPE_ESS;
    else if ((mask & capability) & WLAN_CAPABILITY_IBSS) type = IEEE80211_BSS_TYPE_IBSS;
    if (mask & WLAN_CAPABILITY_PRIVACY)
        privacy = capability & WLAN_CAPABILITY_PRIVACY ? IEEE80211_PRIVACY_ON : IEEE80211_PRIVACY_OFF;
    return cfg80211_get_bss(wiphy, channel, bssid, ssid, ssid_length, type, privacy);
}
static inline void wlan_roamed_bss(struct net_device *device, struct cfg80211_bss *bss,
    const u8 *request, size_t request_length, const u8 *response, size_t response_length,
    gfp_t allocation)
{
    struct cfg80211_roam_info info = {
        .req_ie = request, .req_ie_len = request_length,
        .resp_ie = response, .resp_ie_len = response_length,
    };
    info.links[0].bss = bss;
    cfg80211_roamed(device, &info, allocation);
}
static inline void wlan_show_task_stack(struct task_struct *task)
{
    unsigned long entries[32];
    unsigned int count = stack_trace_save_tsk(task, entries, ARRAY_SIZE(entries), 0);
    stack_trace_print(entries, count, 0);
}''')
source = source.replace('struct cfg80211_sched_scan_request *prSchedScanRequest;',
    'struct cfg80211_sched_scan_request *prSchedScanRequest;\n\tu64 pro6_sched_reqid;')
path.write_text(source)

path = root / 'os/linux/gl_kal.c'
source = path.read_text()
start = source.index('static struct file *filp;')
end = source.index('static PUINT_8 apucFwPath[]', start)
source = source[:start] + 'static const struct firmware *pro6_wifi_firmware;\n\n' + source[end:]

def replace_function(source, name, body):
    pattern = rf'(^WLAN_STATUS {name}\([^\n]*\)\n)\{{.*?^\}}'
    source, count = re.subn(pattern, lambda match: match[1] + '{\n' + body + '\n}',
                            source, count=1, flags=re.M | re.S)
    assert count == 1, name
    return source

source = replace_function(source, 'kalFirmwareOpen', '''    int ret;
    if (!prGlueInfo || !prGlueInfo->prDevHandler || pro6_wifi_firmware)
        return WLAN_STATUS_FAILURE;
    ret = request_firmware_direct(&pro6_wifi_firmware, "WIFI_RAM_CODE_6797",
                                  &prGlueInfo->prDevHandler->dev);
    if (ret) {
        pr_err("PRO6 Wi-Fi firmware request failed: %d\\n", ret);
        return WLAN_STATUS_FAILURE;
    }
    if (!pro6_wifi_firmware->size) {
        release_firmware(pro6_wifi_firmware);
        pro6_wifi_firmware = NULL;
        return WLAN_STATUS_FAILURE;
    }
    return WLAN_STATUS_SUCCESS;''')
source = replace_function(source, 'kalFirmwareClose', '''    release_firmware(pro6_wifi_firmware);
    pro6_wifi_firmware = NULL;
    return WLAN_STATUS_SUCCESS;''')
source = replace_function(source, 'kalFirmwareLoad', '''    if (!pro6_wifi_firmware || !prBuf || !pu4Size ||
        u4Offset > pro6_wifi_firmware->size ||
        *pu4Size > pro6_wifi_firmware->size - u4Offset)
        return WLAN_STATUS_FAILURE;
    memcpy(prBuf, pro6_wifi_firmware->data + u4Offset, *pu4Size);
    return WLAN_STATUS_SUCCESS;''')
source = replace_function(source, 'kalFirmwareSize', '''    if (!pro6_wifi_firmware || !pu4Size || pro6_wifi_firmware->size > U32_MAX)
        return WLAN_STATUS_FAILURE;
    *pu4Size = pro6_wifi_firmware->size;
    return WLAN_STATUS_SUCCESS;''')
# Native kernel file APIs for existing diagnostic/config helpers; no set_fs
# or credentials mutation. Fail explicitly when a path cannot be opened.
source = re.sub(r'^\s*mm_segment_t oldfs;\n', '\n', source, flags=re.M)
source = re.sub(r'^\s*oldfs = get_fs\(\);\n', '\n', source, flags=re.M)
source = re.sub(r'^\s*set_fs\([^\n]*\);\n', '\n', source, flags=re.M)
source = source.replace('ret = vfs_read(file, data, size, &offset);',
    'if (!file || IS_ERR(file)) return -EINVAL;\n\tret = kernel_read(file, data, size, &offset);')
source = source.replace('ret = vfs_write(file, data, size, &offset);',
    'if (!file || IS_ERR(file)) return -EINVAL;\n\tret = kernel_write(file, data, size, &offset);')
source = source.replace('filp_close(file, NULL);', 'if (file && !IS_ERR(file)) filp_close(file, NULL);')
source = re.sub(r'^\s*prNetDev->last_rx = [^\n]+;', '', source, flags=re.M)
source = source.replace('''	init_timer(&(prGlueInfo->tickfn));
	prGlueInfo->tickfn.function = prTimerHandler;
	prGlueInfo->tickfn.data = (unsigned long)prGlueInfo;''',
                        '\ttimer_setup(&prGlueInfo->tickfn, kalTimeoutHandler, 0);')
source = source.replace('P_GLUE_INFO_T prGlueInfo = (P_GLUE_INFO_T) arg;',
                        'P_GLUE_INFO_T prGlueInfo = timer_container_of(prGlueInfo, timer, tickfn);')
source = re.sub(r'(^static int wlan_fb_notifier_callback\([^\n]+\)\n\{.*?^\})',
                r'#ifdef FB_EVENT_BLANK\n\1\n#endif', source, flags=re.M | re.S)
pattern = r'(^INT_32 kalFbNotifierReg\([^\n]+\)\n\{)(.*?)(^\})'
source, count = re.subn(pattern,
    lambda match: match[1] + '\n#ifdef FB_EVENT_BLANK' + match[2] +
                  '#else\n\treturn -EOPNOTSUPP;\n#endif\n' + match[3],
    source, flags=re.M | re.S)
assert count == 1
source = source.replace('fb_unregister_client(&wlan_fb_notifier);',
                        '#ifdef FB_EVENT_BLANK\n\tfb_unregister_client(&wlan_fb_notifier);\n#endif')
path.write_text(source)
