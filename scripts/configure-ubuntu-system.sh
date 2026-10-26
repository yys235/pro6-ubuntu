#!/bin/sh
set -eu
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
install -m755 /tmp/pro6-early-helper /usr/local/sbin/pro6-early-helper
install -m755 /tmp/pro6-adbd /usr/sbin/adbd
install -m644 /proc/1/root/adb_keys /adb_keys
mkdir -p /system/bin /root/.ssh /etc/ssh/sshd_config.d /run/sshd
ln -sf /bin/sh /system/bin/sh
chmod 700 /root/.ssh
install -m600 /tmp/pro6-host.pub /root/.ssh/authorized_keys
printf 'pro6-ubuntu\n' > /etc/hostname
printf '127.0.0.1 localhost\n127.0.1.1 pro6-ubuntu\n::1 localhost ip6-localhost\n' > /etc/hosts
rm -f /etc/apt/apt.conf.d/90pro6-usb-proxy /usr/sbin/policy-rc.d
cat > /etc/ssh/sshd_config.d/10-pro6-local.conf <<'EOF'
ListenAddress 127.0.0.1
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
UseDNS no
EOF
mkdir -p /etc/systemd/system/sysinit.target.wants /etc/systemd/system/multi-user.target.wants
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/system/pro6-usb.service <<'EOF'
[Unit]
Description=PRO6 Ubuntu USB administration
DefaultDependencies=no
Before=sysinit.target shutdown.target
Conflicts=shutdown.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/pro6-early-helper usb-adb
RemainAfterExit=yes
TimeoutStartSec=20
StandardOutput=kmsg
StandardError=kmsg
[Install]
WantedBy=sysinit.target
EOF
cat > /etc/systemd/system/pro6-sshd.service <<'EOF'
[Unit]
Description=PRO6 Ubuntu SSH over the local USB tunnel
After=pro6-usb.service
Wants=pro6-usb.service
[Service]
Type=simple
ExecStartPre=/usr/bin/mkdir -p /run/sshd
ExecStart=/usr/sbin/sshd -D -e
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF
ln -sf ../pro6-usb.service /etc/systemd/system/sysinit.target.wants/pro6-usb.service
ln -sf ../pro6-sshd.service /etc/systemd/system/multi-user.target.wants/pro6-sshd.service
for unit in ssh.socket ssh.service systemd-pstore.service; do
    ln -sf /dev/null "/etc/systemd/system/$unit"
done
ln -sf /usr/lib/systemd/system/multi-user.target /etc/systemd/system/default.target
cat > /etc/systemd/journald.conf.d/pro6.conf <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=16M
ForwardToKMsg=yes
MaxLevelKMsg=info
EOF
printf '# Root storage is prepared by the PRO6 initramfs.\ntmpfs /tmp tmpfs mode=1777,nosuid,nodev,size=64M 0 0\n' > /etc/fstab
/usr/sbin/sshd -t
/usr/bin/ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
/usr/bin/systemd-analyze verify /etc/systemd/system/pro6-usb.service /etc/systemd/system/pro6-sshd.service
printf 'PRO6_UBUNTU_SYSTEM_CONFIGURED\n'
