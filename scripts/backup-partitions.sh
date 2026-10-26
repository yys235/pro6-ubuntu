#!/bin/sh
# 全分区备份：在手机 Android (adb shell, su 0) 上运行，产物经 adb pull 回 PC。
# 用法: sh backup-partitions.sh /sdcard/pro6-backup
set -eu
DEST=${1:-/sdcard/pro6-backup}
mkdir -p "$DEST"

# 关键分区（PRO 6 mz6797 分区号，其他机型勿用）
PARTS="boot:25 recovery:1 lk:23 lk2:24 preloader:21 preloader_backup:22
devinfo:18 frp:14 protect1:2 protect2:3 nvram:4 nvdata:5 nvcfg:6
proinfo:8 para:9 md1img:16 md1dsp:17 md1arm7:18 md1rom:19 md3rom:20
scp1:26 scp2:27 scp_smem:28 efuse:29"

for entry in $PARTS; do
    name=${entry%%:*}; num=${entry##*:}
    dev=/dev/block/mmcblk0p$num
    [ -e "$dev" ] || { echo "skip $name (no p$num)"; continue; }
    size=$(cat /sys/class/block/mmcblk0p$num/size)
    echo "== $name p$num ($((size/2048))KB) =="
    dd if="$dev" of="$DEST/$name.img" bs=1048576 2>/dev/null || dd if="$dev" of="$DEST/$name.img"
    sha1sum "$dev" | cut -d' ' -f1 > "$DEST/$name.sha1"
    sha256sum "$dev" | cut -d' ' -f1 > "$DEST/$name.sha256"
done

# GPT 双份
dd if=/dev/block/mmcblk0 of="$DEST/gpt-primary.bin" bs=512 count=34
dd if=/dev/block/mmcblk0 of="$DEST/gpt-backup.bin" bs=512 skip=$((`cat /sys/block/mmcblk0/size`-34)) count=34

# 清单
python3 - "$DEST" <<'PY'
import json, sys, os, hashlib
d = sys.argv[1]
m = []
for f in sorted(os.listdir(d)):
    if f.endswith('.img') or f.endswith('.bin'):
        p = os.path.join(d, f)
        h1 = hashlib.sha1(open(p,'rb').read()).hexdigest()
        h2 = hashlib.sha256(open(p,'rb').read()).hexdigest()
        m.append({"name": f, "size": os.path.getsize(p), "sha1": h1, "sha256": h2})
json.dump(m, open(os.path.join(d,'manifest.json'),'w'), indent=1)
print(f"manifest: {len(m)} files")
PY
echo "DONE. Now pull: adb pull $DEST"
