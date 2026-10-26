"""Build a small Ubuntu diagnostic initramfs, without touching a device."""
import gzip
import argparse
import hashlib
import json
from pathlib import Path
import stat
import tarfile

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--usb', action='store_true')
parser.add_argument('--name')
parser.add_argument('--systemd', action='store_true')
args = parser.parse_args()
assert not (args.usb and args.systemd), 'Persistent systemd owns USB; do not start an initramfs adbd'
source = ROOT / 'sources/ubuntu-base-26.04.1-base-arm64.tar.gz'
assert hashlib.sha256(source.read_bytes()).hexdigest() == '5a1906794ced63a71a8119c3f211ef5f0bbe0a243001b4bbd41fdf80c5b219fd'
entries = {}
with tarfile.open(source) as tar:
    for name in ('usr/bin/dash', 'usr/lib/aarch64-linux-gnu/libc.so.6',
                 'usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1',
                 'usr/lib/ld-linux-aarch64.so.1', 'usr/lib/os-release',
                 'etc/os-release'):
        member = tar.getmember(name)
        if member.issym():
            entries[name] = (stat.S_IFLNK | member.mode, member.linkname.encode(), 0, 0)
        else:
            assert member.isfile()
            entries[name] = (stat.S_IFREG | member.mode, tar.extractfile(member).read(), 0, 0)
for name in ('dev', 'proc', 'sys', 'run', 'tmp', 'etc', 'usr', 'usr/bin',
             'usr/sbin', 'usr/lib', 'usr/lib/aarch64-linux-gnu'):
    entries[name] = (stat.S_IFDIR | 0o755, b'', 0, 0)
entries['tmp'] = (stat.S_IFDIR | 0o1777, b'', 0, 0)
for name, target in (('bin', 'usr/bin'), ('sbin', 'usr/sbin'), ('lib', 'usr/lib'),
                     ('usr/bin/sh', 'dash')):
    entries[name] = (stat.S_IFLNK | 0o777, target.encode(), 0, 0)
entries['dev/console'] = (stat.S_IFCHR | 0o600, b'', 5, 1)
entries['dev/null'] = (stat.S_IFCHR | 0o666, b'', 1, 3)
for name, path in (('init', 'ubuntu-system-init' if args.systemd else 'ubuntu-early-init'),
                   ('usr/sbin/ubuntu-early-helper', 'ubuntu-early-helper')):
    entries[name] = (stat.S_IFREG | 0o755, (ROOT / 'experiment' / path).read_bytes().replace(b'\r\n', b'\n')
                     if name == 'init' else (ROOT / 'experiment' / path).read_bytes(), 0, 0)
if args.usb:
    for name in ('system', 'system/bin'):
        entries[name] = (stat.S_IFDIR | 0o755, b'', 0, 0)
    entries['system/bin/sh'] = (stat.S_IFLNK | 0o777, b'/bin/sh', 0, 0)
    entries['usr/sbin/adbd'] = (stat.S_IFREG | 0o755, (ROOT / 'evidence/binary-sbin_adbd').read_bytes(), 0, 0)
    key = (Path.home() / '.android/adbkey.pub').read_bytes().split()[0] + b' pro6-ubuntu-host\n'
    entries['adb_keys'] = (stat.S_IFREG | 0o644, key, 0, 0)
    mode, init, major, minor = entries['init']
    init = init.replace(b'/usr/sbin/ubuntu-early-helper reboot-after 45',
                        b'/usr/sbin/ubuntu-early-helper usb-adb >/dev/kmsg 2>&1\n/usr/sbin/ubuntu-early-helper reboot-after 45')
    entries['init'] = mode, init, major, minor
cpio = bytearray()
for ino, (name, (mode, data, major, minor)) in enumerate(
        [*sorted(entries.items()), ('TRAILER!!!', (0, b'', 0, 0))], 1):
    name_bytes = name.encode() + b'\0'
    fields = (ino, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor, len(name_bytes), 0)
    cpio += b'070701' + ''.join(f'{value:08x}' for value in fields).encode() + name_bytes
    cpio += bytes(-len(cpio) % 4)
    cpio += data
    cpio += bytes(-len(cpio) % 4)
output = gzip.compress(cpio, mtime=0)
stem = args.name or ('ubuntu-early-usb' if args.usb else 'ubuntu-early')
assert stem.replace('-', '').isalnum()
(ROOT / 'experiment' / (stem + '.cpio.gz')).write_bytes(output)
report = {'purpose': 'Ubuntu dash/glibc early PID1 diagnostic, not full installed Ubuntu',
          'bytes': len(output), 'sha256': hashlib.sha256(output).hexdigest(),
          'entries': len(entries), 'flashed': False, 'adb_diagnostic': args.usb,
          'persistent_systemd_handoff': args.systemd}
(ROOT / 'experiment' / (stem + '-ramdisk.json')).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
