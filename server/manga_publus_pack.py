"""Publus configuration packs and image paths.

Based on the Apache-2.0 Keiyoushi Publus library.
"""

from base64 import b64decode
from functools import reduce
import json
from operator import xor

from source_parser import SourceError

FILENAME = b'configuration_pack.json'


def substitute(key):
    values = list(range(256))
    j = 0
    for i in range(256):
        j = (j + values[i] + key[i % len(key)]) & 255
        values[i], values[j] = values[j], values[i]
    return values


def stream(key):
    table = substitute(key)
    i = j = 0
    while True:
        i = (i + 1) & 255
        j = (j + table[i]) & 255
        table[i], table[j] = table[j], table[i]
        yield table[(table[i] + table[j]) & 255]


def rc4(value, key):
    return bytearray(byte ^ salt for byte, salt in zip(value, stream(key)))


def swap_blocks(data, start, end, count):
    for i in range(count):
        left, right = start - i, end - i
        data[left], data[right] = data[right], data[left]


def mutate(data, *keys):
    all_keys = b''.join(keys)
    mask = sum(all_keys) & 255
    check = reduce(xor, all_keys, 0)
    shift = (check >> 5) & 7
    flipping = [(width, basis) for bit, width, basis in ((2, 1, 85), (4, 2, 51), (8, 4, 15))
                if not mask & bit]
    if flipping:
        replacements = []
        for byte in range(256):
            for width, basis in flipping:
                byte = ((byte & basis) << width) | ((byte >> width) & basis)
            replacements.append(byte)
        data[:] = data.translate(bytes(replacements))
    for first in range(0, len(data), 32):
        block = data[first:first + 32]
        width = len(block)
        total = (mask + sum(block)) & 255
        check_block = reduce(xor, block, check)
        half = 1
        while half * 2 <= width:
            step = half * 2
            if not total & step:
                # Smaller block exchanges commute with the larger exchanges.
                for end in range(step - 1, width, step):
                    swap_blocks(block, end - half, end, half)
            half = step
        rotate = (check_block >> 3) % width
        if rotate:
            block = block[-rotate:] + block[:-rotate]
        if shift:
            previous = block[-1]
            for i, byte in enumerate(block):
                block[i] = ((previous << (8 - shift)) | (byte >> shift)) & 255
                previous = byte
        data[first:first + width] = block


def reverse_xor(payload, start, key):
    for pos, salt in zip(range(start, -1, -2), stream(key)):
        payload[pos] ^= salt


def decode_pack(encoded):
    try:
        if not isinstance(encoded, str) or not 128 < len(encoded) <= 6 * 1024 * 1024:
            raise ValueError('Invalid pack size')
        packed = b64decode(encoded, validate=True)
        first, second, third = (bytearray(packed[pos:pos + 32]) for pos in range(0, 96, 32))
        data = bytearray(packed[96:])
        mutate(data, first, second, third)
        table = substitute(second + FILENAME + third)
        for index in range(len(data)):
            data[index] ^= table[index & 255]
        reverse_xor(data, (len(data) | 1) - 2, FILENAME + first + second)
        reverse_xor(data, (len(data) - 1) & -2, third + FILENAME + first)
        matrices = (first, second, third, data)
        for i in range(min(32, len(data))):
            mix = data[i] ^ first[i] ^ second[i] ^ third[i]
            for low, high in ((0, 2), (4, 6)):
                left, right = matrices[(mix >> low) & 3], matrices[(mix >> high) & 3]
                left[i], right[i] = right[i], left[i]
        third = rc4(third, second + first + FILENAME)
        second = rc4(second, first + FILENAME + third)
        first = rc4(first, FILENAME + third + second)
        mutate(third, first, second)
        mutate(second, first, third)
        mutate(first, second, third)
        result = json.loads(rc4(data, third + second + FILENAME))
        if not isinstance(result, dict):
            raise ValueError('Invalid pack payload')
        return result, (bytes(first), bytes(second), bytes(third))
    except (UnicodeError, ValueError, RecursionError):
        raise SourceError('Publus не предоставил корректную конфигурацию выпуска.') from None


def image_path(page, number, keys=()):
    if not keys:
        return f'{page}/{number}.jpeg'
    prefix = page + '/'
    suffix = str(number)
    data = b'\x00;' + (prefix + suffix).encode('utf-16-be')
    offset = len(data) - len(suffix) * 2
    rounds = 3
    volume = len(suffix) * 2 + 2 * len(data)
    while volume < 256:
        rounds += 1
        volume += len(data)
    mixed = bytes(x ^ y ^ z for x, y, z in zip(*keys))
    high, mid, low = 1670739, 1282576, 2237221
    pos = 0
    for _ in range(rounds):
        for idx in range(offset, len(data)):
            low ^= data[idx] ^ mixed[pos & 31]
            multiplied = 435 * low
            middle = 435 * mid + ((low & 7) << 18) + (multiplied >> 22)
            high = (435 * high + ((mid & 3) << 19) + ((low & 4194296) >> 3) + (middle >> 21)) & 2097151
            low, mid = multiplied & 4194303, middle & 2097151
            pos += 1
        offset = 0
    hashed = (high << 43) | (mid << 22) | low
    result = bytes(byte ^ salt for byte, salt in zip(hashed.to_bytes(8, 'big'), mixed))
    return prefix + '10' + result.hex() + '.jpeg'
