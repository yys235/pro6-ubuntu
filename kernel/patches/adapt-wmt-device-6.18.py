"""Migrate WMT device APIs and firmware loading without legacy address limits."""
from pathlib import Path
import re

path = Path('/root/pro6-linux/mt6797-wmt-port/linux/pri/wmt_dev.c')
source = path.read_text()
source = source.replace('#else\n\nstatic struct notifier_block wmt_fb_notifier;',
                        '#elif defined(FB_EVENT_BLANK)\n\nstatic struct notifier_block wmt_fb_notifier;')
source = source.replace('#else\n\twmt_fb_notifier.notifier_call',
                        '#elif defined(FB_EVENT_BLANK)\n\twmt_fb_notifier.notifier_call')
source = source.replace('#else\n\tfb_unregister_client',
                        '#elif defined(FB_EVENT_BLANK)\n\tfb_unregister_client')
source = source.replace('class_create(THIS_MODULE, "stpwmt")', 'class_create("stpwmt")')
for name in ['wmt_dbg_fops', 'wmt_aee_fops']:
    pattern = rf'static const struct file_operations {name} = \{{.*?\n\t\}};'
    match = re.search(pattern, source, re.S)
    assert match
    block = match.group().replace('struct file_operations', 'struct proc_ops')
    block = block.replace('\t\t.owner = THIS_MODULE,\n', '')
    block = block.replace('.read =', '.proc_read =').replace('.write =', '.proc_write =')
    source = source[:match.start()] + block + source[match.end():]

def replace_function(name, replacement):
    global source
    pattern = rf'(?:INT32|MTK_WCN_BOOL) {name}\(.*?\n\{{.*?\n\}}'
    source, count = re.subn(pattern, lambda m: replacement, source, flags=re.S)
    assert count == 1, name

replace_function('wmt_dev_read_file', '''INT32 wmt_dev_read_file(PUINT8 pName, const PPUINT8 ppBufPtr, INT32 offset, INT32 padSzBuf)
{
	const struct firmware *firmware;
	size_t length, headroom;
	int ret;
	if (!pName || !ppBufPtr || offset < 0 || padSzBuf < 0)
		return -EINVAL;
	*ppBufPtr = NULL;
	ret = request_firmware_direct(&firmware, kbasename((char *)pName), wmt_dev);
	if (ret)
		return ret;
	if (firmware->size > INT_MAX || offset > firmware->size) {
		ret = -EFBIG;
		goto release;
	}
	length = firmware->size - offset;
	headroom = max_t(size_t, padSzBuf, BCNT_PATCH_BUF_HEADROOM);
	*ppBufPtr = vzalloc(ALIGN(length + headroom, 4));
	if (!*ppBufPtr) {
		ret = -ENOMEM;
		goto release;
	}
	memcpy(*ppBufPtr + padSzBuf, firmware->data + offset, length);
	ret = length;
release:
	release_firmware(firmware);
	return ret;
}''')
replace_function('wmt_dev_patch_get', '''INT32 wmt_dev_patch_get(PUINT8 pPatchName, osal_firmware **ppPatch, INT32 padSzBuf)
{
	osal_firmware *patch;
	int length;
	if (!ppPatch || !pPatchName || !*pPatchName || padSzBuf < 0)
		return -EINVAL;
	if (*ppPatch) {
		vfree((*ppPatch)->data);
		kfree(*ppPatch);
		*ppPatch = NULL;
	}
	patch = kzalloc(sizeof(*patch), GFP_KERNEL);
	if (!patch)
		return -ENOMEM;
	length = wmt_dev_read_file(pPatchName, (const PPUINT8)&patch->data, 0, padSzBuf);
	if (length <= 0) {
		vfree(patch->data);
		kfree(patch);
		return length ? length : -EINVAL;
	}
	patch->size = length;
	*ppPatch = patch;
	return 0;
}''')
replace_function('wmt_dev_is_file_exist', '''MTK_WCN_BOOL wmt_dev_is_file_exist(PUINT8 pFileName)
{
	const struct firmware *firmware;
	bool present;
	if (!pFileName || !*pFileName)
		return MTK_WCN_BOOL_FALSE;
	if (request_firmware_direct(&firmware, kbasename((char *)pFileName), wmt_dev))
		return MTK_WCN_BOOL_FALSE;
	present = firmware->size > 0;
	release_firmware(firmware);
	return present;
}''')
path.write_text(source)
