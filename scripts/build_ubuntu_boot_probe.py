"""Package a recovery-only Ubuntu diagnostic; never flash from this script."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--kernel', type=Path, help='Image.gz (requires --dtb); omit to retain stock kernel/DTB')
parser.add_argument('--dtb', type=Path)
parser.add_argument('--name', required=True)
parser.add_argument('--no-uart', action='store_true', help='omit unverified early UART accesses')
parser.add_argument('--ramdisk', type=Path, default=ROOT / 'experiment/ubuntu-early.cpio.gz')
parser.add_argument('--cpus', type=int, choices=(1, 8), default=1)
parser.add_argument('--memory', choices=('480M', '1G', 'auto'), default='480M')
parser.add_argument('--target', choices=('boot', 'recovery'), default='recovery')
parser.add_argument('--pad-to-partition', action='store_true')
args = parser.parse_args()
assert args.name.replace('-', '').isalnum()
assert bool(args.kernel) == bool(args.dtb)
stock = (ROOT / 'evidence/recovery-reconstructed.img').read_bytes()
page = struct.unpack_from('<I', stock, 36)[0]
assert stock[:8] == b'ANDROID!' and page == 2048
kernel = (args.kernel.read_bytes() + args.dtb.read_bytes() if args.kernel else
          stock[page:page + struct.unpack_from('<I', stock, 8)[0]])
ramdisk = args.ramdisk.read_bytes()
header = bytearray(stock[:page])
struct.pack_into('<I', header, 8, len(kernel))
struct.pack_into('<I', header, 16, len(ramdisk))
struct.pack_into('<I', header, 24, 0)
if args.kernel:
    # LK constructs the final command line from the Android header.
    command = (b'console=tty0 earlycon=uart8250,mmio32,0x11002000,921600n8 '
               b'keep_bootcon loglevel=8 ignore_loglevel maxcpus=1 mem=480M '
               b'clk_ignore_unused pd_ignore_unused panic=30 rdinit=/init '
               b'bootopt=64S3,32N2,64N2')
    if args.no_uart:
        # Live V3 proved LK truncates long header arguments. Keep the
        # necessary boot controls inside its observed short-copy boundary.
        command = (b'bootopt=64S3,32N2,64N2 panic=30 maxcpus=1 mem=480M '
                   b'clk_ignore_unused pd_ignore_unused')
        command = command.replace(b'maxcpus=1', f'maxcpus={args.cpus}'.encode())
        if args.memory == 'auto':
            command = command.replace(b'mem=480M ', b'')
        elif args.memory != '480M':
            command = command.replace(b'mem=480M', f'mem={args.memory}'.encode())
        assert len(command) <= 96
    assert len(command) < 512
    header[64:576] = command.ljust(512, b'\0')
    # Modern Image text_offset=0 requires a 2 MiB aligned placement.
    struct.pack_into('<I', header, 12, 0x40200000)
digest = hashlib.sha1()
for blob in (kernel, ramdisk, b''):
    digest.update(blob)
    digest.update(struct.pack('<I', len(blob)))
header[576:608] = digest.digest() + bytes(12)
image = bytes(header)
for blob in (kernel, ramdisk):
    image += blob + bytes(-len(blob) % page)

def der(tag, value):
    size = len(value)
    length = bytes([size]) if size < 128 else size.to_bytes((size.bit_length() + 7)//8, 'big')
    if size >= 128:
        length = bytes([0x80 | len(length)]) + length
    return bytes([tag]) + length + value

def integer(value):
    data = value.to_bytes(max(1, (value.bit_length()+7)//8), 'big')
    return der(2, b'\0' + data if data[0] & 0x80 else data)

cert = x509.load_pem_x509_certificate((ROOT / 'evidence/public-aosp-verity.x509.pem').read_bytes())
assert cert.fingerprint(hashes.SHA256()).hex() == '8ad127abae8285b582ea36745f220ab8fe397ffb3b068df19ca22d122c7b3b86'
key = serialization.load_der_private_key((ROOT / 'evidence/public-aosp-verity.pk8').read_bytes(), None)
attrs = der(0x30, der(0x13, ('/' + args.target).encode()) + integer(len(image)))
signature = key.sign(image + attrs, padding.PKCS1v15(), hashes.SHA256())
cert.public_key().verify(signature, image + attrs, padding.PKCS1v15(), hashes.SHA256())
image += der(0x30, integer(1) + cert.public_bytes(serialization.Encoding.DER)
             + bytes.fromhex('300b06092a864886f70d01010b') + attrs + der(4, signature))
partition_size = (16 if args.target == 'boot' else 30) * 1024 * 1024
assert len(image) <= partition_size
if args.pad_to_partition:
    image = image.ljust(partition_size, b'\0')
output = ROOT / 'experiment' / (args.name + '.img')
output.write_bytes(image)
report = {'file': output.name, 'bytes': len(image), 'sha256': hashlib.sha256(image).hexdigest(),
          'stock_kernel': not bool(args.kernel), 'ubuntu_early_ramdisk': True,
          'recovery_only': args.target == 'recovery', 'target': args.target,
          'signature_verified': True, 'public_test_key': True,
          'flashed': False, 'fully_installed_ubuntu': False}
output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
