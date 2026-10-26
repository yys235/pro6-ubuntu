#!/system/bin/sh
set -e
base=/data/pro6-ubuntu
test -f "$base/etc/os-release"
mount -o bind /dev "$base/dev"
mount -t proc proc "$base/proc"
mount -t sysfs sysfs "$base/sys"
printf '%s\n' 'Acquire::http::Proxy "http://127.0.0.1:18081";' > "$base/etc/apt/apt.conf.d/90pro6-usb-proxy"
printf '#!/bin/sh\nexit 101\n' > "$base/usr/sbin/policy-rc.d"
chmod 755 "$base/usr/sbin/policy-rc.d"
# This staging kernel has Android's paranoid-network policy. _apt lacks its
# required network group. Keep repository authentication; run this staging
# download as root without changing Ubuntu's permanent sandbox configuration.
chroot "$base" /usr/bin/apt-get -o APT::Sandbox::User=root -o Acquire::Retries=1 -o Acquire::Languages=none update
