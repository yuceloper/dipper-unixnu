"""Read-only UDIF compatibility reader for the legacy UniXNU build.

Adapted from johnpanos/UniXNU 3baf9f532e60bd4d8ae4e7da2d66a2714b8b4323.
"""
import bz2
import lzma
import plistlib
import shutil
import struct
import subprocess
import sys
import zlib

MACOS = sys.platform == "darwin"
Error = RuntimeError
CHUNK = 8 << 20
SECTOR = 512
ZERO, RAW, IGNORE, ZLIB, BZIP2, LZFSE, LZMA, COMMENT, END = 0, 1, 2, 0x80000005, 0x80000006, 0x80000007, 0x80000008, 0x7ffffffe, 0xffffffff

def udif(dmg):
    """The koly trailer of a UDIF image, or None for a raw image."""
    with open(dmg, 'rb') as handle:
        handle.seek(-512, 2)
        koly = handle.read(512)
    return koly if koly[:4] == b'koly' else None


def image_size(dmg):
    if MACOS:
        info = subprocess.run(['hdiutil', 'imageinfo', '-plist', str(dmg)], capture_output=True, check=True).stdout
        return plistlib.loads(info)['Size Information']['Total Bytes']
    koly = udif(dmg)
    return struct.unpack_from('>Q', koly, 0x1ec)[0] * SECTOR if koly else dmg.stat().st_size


def udif_chunks(handle, koly):
    """The block chunks in disk order, each (type, first byte, byte count, data offset, data length, block index),
    and the CRC32 of each block table, which covers its expanded data except the ignored chunks (None if not CRC32)."""
    xml_offset, xml_length = struct.unpack_from('>QQ', koly, 0xd8)
    handle.seek(xml_offset)
    chunks, crcs = [], []
    for block_index, block in enumerate(plistlib.loads(handle.read(xml_length))['resource-fork']['blkx']):
        mish = block['Data']
        if mish[:4] != b'mish':
            raise Error('UDIF block table without mish header')
        first, data_offset = struct.unpack_from('>Q', mish, 8)[0], struct.unpack_from('>Q', mish, 0x18)[0]
        kind, _ = struct.unpack_from('>II', mish, 0x40)
        crcs.append(struct.unpack_from('>I', mish, 0x48)[0] if kind == 2 else None)
        for index in range(struct.unpack_from('>I', mish, 0xc8)[0]):
            kind, _, sector, count, offset, length = struct.unpack_from('>IIQQQQ', mish, 0xcc + 40 * index)
            if kind not in (COMMENT, END):
                chunks.append((kind, (first + sector) * SECTOR, count * SECTOR, data_offset + offset, length, block_index))
    return sorted(chunks, key=lambda chunk: chunk[1]), crcs


def lzfse(data):
    decoder = shutil.which('lzfse')
    if not decoder:
        raise Error(f'lzfse not found on PATH (brew install lzfse); it decodes the UDIF disk image')
    return subprocess.run([decoder, '-decode'], input=data, capture_output=True, check=True).stdout


def read_image(dmg, size):
    """The bytes of the attached disk image, in pieces: expanded UDIF chunks, or the raw file."""
    koly = udif(dmg)
    with open(dmg, 'rb') as handle:
        if not koly:
            while data := handle.read(CHUNK):
                yield data
            return
        chunks, want = udif_chunks(handle, koly)
        crcs = [0] * len(want)
        cursor = 0
        for kind, start, count, offset, length, block in chunks:
            if start != cursor:
                raise Error(f'{dmg.name}: UDIF chunks leave a gap or overlap at {cursor:#x}')
            if kind in (ZERO, IGNORE):
                data = bytes(count)
            else:
                handle.seek(offset)
                packed = handle.read(length)
                decode = {RAW: bytes, ZLIB: zlib.decompress, BZIP2: bz2.decompress, LZFSE: lzfse, LZMA: lzma.decompress}.get(kind)
                if not decode:
                    raise Error(f'{dmg.name}: UDIF chunk type {kind:#x} is not supported')
                data = decode(packed)
            if len(data) != count:
                raise Error(f'{dmg.name}: UDIF chunk at {start:#x} expands to {len(data)} bytes, not {count}')
            if kind != IGNORE:
                crcs[block] = zlib.crc32(data, crcs[block])
            yield data
            cursor += count
        if cursor != size:
            raise Error(f'{dmg.name}: UDIF chunks cover {cursor} bytes of {size}')
        for block, (got, expected) in enumerate(zip(crcs, want)):
            if expected is not None and got != expected:
                raise Error(f'{dmg.name}: UDIF block table {block} CRC32 {got:08x}, expected {expected:08x}')


