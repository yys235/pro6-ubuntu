#!/bin/sh
set -eu
image=/tmp/ubuntu-pro6-6-18-default.img
expected=c4c78566850879d645bea82ecb1784cc7a996566f1a6d112bc06b3d749396ec3
test "$(cat /sys/class/block/mmcblk0p25/size)" = 32768
grep -qx PARTNAME=boot /sys/class/block/mmcblk0p25/uevent
test "$(sha1sum /dev/mmcblk0p25 | cut -d' ' -f1)" = c2ad83e374f14a099d44bacb9e310c585f184489
test "$(sha256sum "$image" | cut -d' ' -f1)" = "$expected"
test "$(stat -c %s "$image")" = 16777216
dd if="$image" of=/dev/mmcblk0p25 bs=1048576 conv=fsync
actual=$(sha256sum /dev/mmcblk0p25 | cut -d' ' -f1)
test "$actual" = "$expected"
printf 'BOOT_WRITE_READBACK_PASS sha256=%s\n' "$actual"
sync
