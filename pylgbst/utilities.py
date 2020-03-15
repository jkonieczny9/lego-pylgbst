"""
This module offers some utilities, in a way they are work in both Python 2 and 3
"""

import binascii
import logging
import sys
from struct import unpack

log = logging.getLogger(__name__)

if sys.version_info[0] == 2:
    import Queue as queue
else:
    import queue as queue

queue = queue  # just to use it


def check_unpack(seq, index, pattern, size):
    """Check that we got size bytes, if so, unpack using pattern"""
    data = seq[index: index + size]
    assert len(data) == size, "Unexpected data len %d, expected %d" % (len(data), size)
    return unpack(pattern, data)[0]


def usbyte(seq, index):
    return check_unpack(seq, index, "<B", 1)

def sbyte(seq, index):
    return check_unpack(seq, index, "<b", 1)

def ushort(seq, index):
    return check_unpack(seq, index, "<H", 2)

def sshort(seq, index):
    return check_unpack(seq, index, "<h", 2)

def usint(seq, index):
    return check_unpack(seq, index, "<I", 4)

def sint(seq, index):
    return check_unpack(seq, index, "<i", 4)

def sfloat(seq, index):
    return check_unpack(seq, index, "<f", 4)

def sdouble(seq, index):
    return check_unpack(seq, index, "<d", 8)

def hex2int(data):
    return int(data, 16)

def str2hex(data):  # we need it for python 2+3 compatibility
    # if sys.version_info[0] == 3:
    # data = bytes(data, 'ascii')
    if not isinstance(data, (bytes, bytearray)):
        data = bytes(data, "ascii")
    hexed = binascii.hexlify(data)
    return hexed

def data2hex(data, min_size=2):
    hex_str = hex(data)[2:]
    while len(hex_str) < min_size:
        hex_str += "0"
    return "0x"+hex_str

def decode_mac(data):
    mac_str = str2hex(data)
    assert(len(mac_str) % 2 == 0)
    return (":".join([mac_str[i:i+2] for i in range(0, len(mac_str), 2)])).upper()

def decode_version(data):
    major_version = data2hex(usbyte(data, 3), 2)[2:3]
    minor_version = data2hex(usbyte(data, 3), 2)[3:4]
    bug_fixing_number = data2hex(usbyte(data, 2), 2)[2:]
    build_number = data2hex(ushort(data, 0), 4)[2:]
    version = ".".join([major_version, minor_version, bug_fixing_number, build_number])
    return version

    