#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# BFWAV Endian Converter — core logic
# Based on BCFSTM-BCFWAV Converter v2.1 by AboodXD (GPL-3.0)
# GUI wrapper by Samuel Dyson
#

import struct as _struct


# ── bytes helpers ────────────────────────────────────────────────────────────

def bytes_to_string(data):
    end = data.find(b'\0')
    if end == -1:
        return data.decode('utf-8')
    return data[:end].decode('utf-8')


def to_bytes(inp, length=1, bom='>'):
    if isinstance(inp, bytearray):
        return bytes(inp)
    elif isinstance(inp, int):
        return inp.to_bytes(length, 'big' if bom == '>' else 'little')
    elif isinstance(inp, str):
        return inp.encode('utf-8').ljust(length, b'\0')


# ── structs ──────────────────────────────────────────────────────────────────

class Header(_struct.Struct):
    def __init__(self, bom):
        super().__init__(bom + '4s2xH2I2H')

    def data(self, data, pos):
        (self.magic, self.size_, self.version,
         self.fileSize, self.numBlocks, self.reserved) = self.unpack_from(data, pos)


class BLKHeader(_struct.Struct):
    def __init__(self, bom):
        super().__init__(bom + '4sI')

    def data(self, data, pos):
        (self.magic, self.size_) = self.unpack_from(data, pos)


class WAVInfo(_struct.Struct):
    def __init__(self, bom):
        super().__init__(bom + '2B2x4I')

    def data(self, data, pos):
        (self.codec, self.loop_flag, self.sample,
         self.loop_start, self.loop_end, self.reserved) = self.unpack_from(data, pos)


class Ref(_struct.Struct):
    def __init__(self, bom):
        super().__init__(bom + 'H2xi')

    def data(self, data, pos):
        (self.type_, self.offset) = self.unpack_from(data, pos)


class DSPContext(_struct.Struct):
    def __init__(self, bom):
        super().__init__(bom + '3H')

    def data(self, data, pos):
        (self.predictor_scale, self.preSample,
         self.preSample2) = self.unpack_from(data, pos)


class IMAContext(_struct.Struct):
    def __init__(self, bom):
        super().__init__(bom + 'hH')

    def data(self, data, pos):
        (self.data_, self.tableIndex) = self.unpack_from(data, pos)


# ── conversion ───────────────────────────────────────────────────────────────

def get_bom(data):
    if data[4:6] == b'\xFF\xFE':
        return '<'
    elif data[4:6] == b'\xFE\xFF':
        return '>'
    return None


def is_little_endian(data):
    return data[4:6] == b'\xFF\xFE'


def convert_fwav_to_little_endian(f):
    """
    Convert a BFWAV file (bytes) to little-endian.
    Returns the converted bytes, or raises ValueError on failure.
    """
    magic = bytes_to_string(f[:4])
    if magic not in ('FWAV', 'CWAV'):
        raise ValueError(f'Not a BFWAV/BCWAV file (magic: {magic!r})')

    bom = get_bom(f)
    if bom is None:
        raise ValueError('Invalid BOM in file header')

    if bom == '<':
        # Already little-endian — return unchanged
        return bytes(f), False

    dest      = magic          # keep same magic
    dest_bom  = '<'            # target: little-endian

    outputBuffer = bytearray(len(f))
    pos = 0

    dest_ver = {'FWAV': 0x10100, 'CWAV': 0x2010000}

    header = Header(bom)
    header.data(f, pos)
    dest_ver[dest] = header.version   # preserve original version

    outputBuffer[pos:pos + header.size] = bytes(
        Header(dest_bom).pack(
            to_bytes(dest, 4), header.size_, dest_ver[dest],
            header.fileSize, header.numBlocks, header.reserved
        )
    )
    outputBuffer[4:6] = b'\xFF\xFE'   # little-endian BOM

    pos += header.size
    sized_refs = {}

    for i in range(1, header.numBlocks + 1):
        sized_refs[i] = Ref(bom)
        sized_refs[i].data(f, pos + 12 * (i - 1))

        outputBuffer[pos + 12*(i-1):pos + 12*(i-1) + sized_refs[i].size] = bytes(
            Ref(dest_bom).pack(sized_refs[i].type_, sized_refs[i].offset)
        )

        block_size = _struct.unpack(bom + 'I', f[pos + 12*(i-1) + 8:pos + 12*i])[0]
        sized_refs[i].block_size = block_size
        outputBuffer[pos + 12*(i-1) + 8:pos + 12*i] = to_bytes(block_size, 4, dest_bom)

    if sized_refs[1].type_ != 0x7000 or sized_refs[1].offset in (0, -1):
        raise ValueError('Unexpected block layout (INFO block missing)')

    pos = sized_refs[1].offset

    info = BLKHeader(bom)
    info.data(f, pos)
    outputBuffer[pos:pos + info.size] = bytes(BLKHeader(dest_bom).pack(info.magic, info.size_))
    pos += info.size

    wavInfo = WAVInfo(bom)
    wavInfo.data(f, pos)
    outputBuffer[pos:pos + wavInfo.size] = bytes(
        WAVInfo(dest_bom).pack(
            wavInfo.codec, wavInfo.loop_flag,
            wavInfo.sample, wavInfo.loop_start, wavInfo.loop_end, wavInfo.reserved
        )
    )
    pos += wavInfo.size

    count = _struct.unpack(bom + 'I', f[pos:pos + 4])[0]
    outputBuffer[pos:pos + 4] = to_bytes(count, 4, dest_bom)
    countPos = pos

    channelInfoTable = {}
    sampleData_ref   = {}
    ADPCMInfo_ref    = {}
    param            = {}

    for i in range(1, count + 1):
        pos = countPos + 4
        channelInfoTable[i] = Ref(bom)
        channelInfoTable[i].data(f, pos + 8 * (i - 1))

        outputBuffer[pos + 8*(i-1):pos + 8*(i-1) + channelInfoTable[i].size] = bytes(
            Ref(dest_bom).pack(channelInfoTable[i].type_, channelInfoTable[i].offset)
        )

        if channelInfoTable[i].offset not in (0, -1):
            pos = channelInfoTable[i].offset + countPos
            sampleData_ref[i] = Ref(bom)
            sampleData_ref[i].data(f, pos)
            outputBuffer[pos:pos + sampleData_ref[i].size] = bytes(
                Ref(dest_bom).pack(sampleData_ref[i].type_, sampleData_ref[i].offset)
            )

            pos += 8
            ADPCMInfo_ref[i] = Ref(bom)
            ADPCMInfo_ref[i].data(f, pos)
            outputBuffer[pos:pos + ADPCMInfo_ref[i].size] = bytes(
                Ref(dest_bom).pack(ADPCMInfo_ref[i].type_, ADPCMInfo_ref[i].offset)
            )

            if ADPCMInfo_ref[i].offset not in (0, -1):
                pos = ADPCMInfo_ref[i].offset + pos - 8
                if ADPCMInfo_ref[i].type_ == 0x0300:
                    for j in range(16):
                        param[j] = _struct.unpack(bom + 'H', f[pos + 2*j:pos + 2*j + 2])[0]
                        outputBuffer[pos + 2*j:pos + 2*j + 2] = to_bytes(param[j], 2, dest_bom)
                    pos += 32

                    context = DSPContext(bom)
                    context.data(f, pos)
                    outputBuffer[pos:pos + context.size] = bytes(
                        DSPContext(dest_bom).pack(context.predictor_scale, context.preSample, context.preSample2)
                    )
                    pos += context.size

                    loopContext = DSPContext(bom)
                    loopContext.data(f, pos)
                    outputBuffer[pos:pos + loopContext.size] = bytes(
                        DSPContext(dest_bom).pack(loopContext.predictor_scale, loopContext.preSample, loopContext.preSample2)
                    )
                    pos += loopContext.size + 2

                elif ADPCMInfo_ref[i].type_ == 0x0301:
                    context = IMAContext(bom)
                    context.data(f, pos)
                    outputBuffer[pos:pos + context.size] = bytes(
                        IMAContext(dest_bom).pack(context.data_, context.tableIndex)
                    )
                    pos += context.size

                    loopContext = IMAContext(bom)
                    loopContext.data(f, pos)
                    outputBuffer[pos:pos + loopContext.size] = bytes(
                        IMAContext(dest_bom).pack(loopContext.data_, loopContext.tableIndex)
                    )

    for i in range(1, header.numBlocks + 1):
        if sized_refs[i].offset not in (0, -1):
            if sized_refs[i].type_ == 0x7001:
                pos = sized_refs[i].offset
                data_blk = BLKHeader(bom)
                data_blk.data(f, pos)
                outputBuffer[pos:pos + data_blk.size] = bytes(
                    BLKHeader(dest_bom).pack(data_blk.magic, data_blk.size_)
                )
                pos += data_blk.size
                raw = f[pos:pos + data_blk.size_ - 8]

                if wavInfo.codec == 1:
                    # PCM16 — swap sample pairs
                    swapped = bytearray(len(raw))
                    for k in range(0, len(raw) - 1, 2):
                        swapped[k]     = raw[k + 1]
                        swapped[k + 1] = raw[k]
                    outputBuffer[pos:pos + len(raw)] = swapped
                else:
                    outputBuffer[pos:pos + len(raw)] = raw

    return bytes(outputBuffer), True


def process_file(path):
    """
    Read, convert, and overwrite a .bfwav file in-place.
    Returns (converted: bool, message: str).
    """
    with open(path, 'rb') as fh:
        data = fh.read()

    result, changed = convert_fwav_to_little_endian(data)

    if changed:
        with open(path, 'wb') as fh:
            fh.write(result)
        return True, 'Converted to little-endian'
    else:
        return False, 'Already little-endian — skipped'
