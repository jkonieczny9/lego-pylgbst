import logging
import time
from struct import pack, unpack

from pylgbst.utilities import str2hex

#-------------------------------------------------------------------------

log = logging.getLogger('hub')

#-------------------------------------------------------------------------

LEGO_MANUFACTURER_ID = 0x0397

class BLEManufacturerData(object):
    WEDO2_ID = 0x00
    DUPLO_TRAIN_BASE_ID = 0x20
    MOVE_HUB_ID = 0x40
    POWERED_UP_HUB_ID = 0x41
    POWERED_UP_REMOTE_CONTROL_ID = 0x42
    TECHNIC_HUB_ID = 0x80


class Message(object):
    TYPE = None

    def __init__(self):
        self.hub_id = 0x00  # not used according to official doc
        self.payload = b""

    def bytes(self):
        """
        see https://lego.github.io/lego-ble-wireless-protocol-docs/#common-message-header
        """
        msglen = len(self.payload) + 3
        if msglen > 127:
            #128: 128 + 1
            #129: 129 + 1
            #...
            #255: 255 + 1
            #256: 255 + 2
            #...
            #509: 255 + 255
            msglen_bytes = pack("<B", min(msglen, 255)) + pack("<B", max(msglen-255, 0)+1)
        else:
            msglen_bytes = pack("<B", msglen)
        return msglen_bytes + pack("<B", self.hub_id) + pack("<B", self.TYPE) + self.payload

    def __repr__(self):
        # assert self.bytes()  # to trigger any field changes
        data = self.__dict__
        data = {x: (str2hex(y) if isinstance(y, bytes)
                else  y if isinstance(y, (bytearray, bool)) or y is None
                else "0x%x" % y)
                for x, y in data.items()
                if x not in ('hub_id',)}
        return self.__class__.__name__ + "(%s)" % data


class DownstreamMsg(Message):

    def __init__(self):
        super(DownstreamMsg, self).__init__()
        self.needs_reply = False

    def is_reply(self, msg):
        del msg
        return False


class UpstreamMsg(Message):

    def __init__(self):
        super(UpstreamMsg, self).__init__()
        self.timestamp = None #Timestamp representing moment of decoding the message

    @classmethod
    def decode(cls, data):
        """
        see https://lego.github.io/lego-ble-wireless-protocol-docs/#common-message-header
        """
        msg = cls()
        msg.timestamp = time.time()
        msg.payload = data
        msglen = msg._byte()
        if msglen > 127:
            msglen = msg._byte() + msglen - 1
        hub_id = msg._byte()
        assert hub_id == 0
        msg_type = msg._byte()
        assert cls.TYPE == msg_type, "Message type does not match: %x!=%x" % (cls.TYPE, msg_type)
        assert isinstance(msg.payload, (bytes, bytearray))
        return msg

    def __shift(self, vtype, vlen):
        val = self.payload[0:vlen]
        self.payload = self.payload[vlen:]
        return unpack("<" + vtype, val)[0]

    def _byte(self):
        return self.__shift("B", 1)

    def _short(self):
        return self.__shift("H", 2)

    def _long(self):
        return self.__shift("I", 4)

    def _float(self):
        return self.__shift("f", 4)

    def _bits_list(self, val):
        res = []
        x = 1
        for i in range(16 + 1):
            if val & x:
                res.append(i)
            x <<= 1
        return res


class MsgHubProperties(DownstreamMsg, UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#hub-properties
    """
    TYPE = 0x01

    ADVERTISE_NAME = 0x01
    BUTTON = 0x02
    FW_VERSION = 0x03 #Firmware version
    HW_VERSION = 0x04 #Hardware version
    RSSI = 0x05
    VOLTAGE_PERC = 0x06 #Battery level
    BATTERY_TYPE = 0x07
    MANUFACTURER = 0x08
    RADIO_FW_VERSION = 0x09
    WIRELESS_PROTO_VERSION = 0x0A
    SYSTEM_TYPE_ID = 0x0B #Hub type ID
    HW_NETW_ID = 0x0C
    PRIMARY_MAC = 0x0D #Primary MAC address
    SECONDARY_MAC = 0x0E
    HARDWARE_NETWORK_FAMILY = 0x0F

    SET = 0x01
    UPD_ENABLE = 0x02
    UPD_DISABLE = 0x03
    RESET = 0x04
    UPD_REQUEST = 0x05
    UPSTREAM_UPDATE = 0x06

    BUTTON_STATE_RELEASED = 0x00
    BUTTON_STATE_UP = 0x01
    BUTTON_STATE_PRESSED = 0x02
    BUTTON_STATE_STOP = 0x7F
    BUTTON_STATE_DOWN = 0xFF

    def __init__(self, prop=None, operation=None, parameters=b""):
        super(MsgHubProperties, self).__init__()

        self.property = prop
        self.operation = operation
        self.parameters = parameters

    def bytes(self):
        if self.operation in (self.UPD_REQUEST, self.UPD_ENABLE):
            self.needs_reply = True
        self.payload = pack("<B", self.property) + pack("<B", self.operation) + self.parameters
        return super(MsgHubProperties, self).bytes()

    @classmethod
    def decode(cls, data):
        msg = super(MsgHubProperties, cls).decode(data)
        assert isinstance(msg, MsgHubProperties)
        msg.property = msg._byte()
        msg.operation = msg._byte()
        msg.parameters = msg.payload
        return msg

    def is_reply(self, msg):
        return isinstance(msg, MsgHubProperties) \
               and msg.operation == self.UPSTREAM_UPDATE and msg.property == self.property


class MsgHubAction(DownstreamMsg, UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#hub-actions
    """
    TYPE = 0x02

    SWITCH_OFF = 0x01
    DISCONNECT = 0x02
    VCC_PORT_CONTROL_ON = 0x03
    VCC_PORT_CONTROL_OFF = 0x04
    BUSY_INDICATION_ON = 0x05
    BUSY_INDICATION_OFF = 0x06
    SWITCH_OFF_IMMEDIATELY = 0x2F

    UPSTREAM_SHUTDOWN = 0x30
    UPSTREAM_DISCONNECT = 0x31
    UPSTREAM_BOOT_MODE = 0x32

    def __init__(self, action=None):
        super(MsgHubAction, self).__init__()
        self.action = action

    def bytes(self):
        self.payload = pack("<B", self.action)
        self.needs_reply = self.action in (self.DISCONNECT, self.SWITCH_OFF)
        return super(MsgHubAction, self).bytes()

    def is_reply(self, msg):
        if not isinstance(msg, MsgHubAction):
            #raise TypeError("Unexpected message type: %s" % (msg.__class__,))
            return False

        if self.action == self.DISCONNECT and msg.action == self.UPSTREAM_DISCONNECT:
            return True
        elif self.action == self.SWITCH_OFF and msg.action == self.UPSTREAM_SHUTDOWN:
            return True
        else:
            return False

    @classmethod
    def decode(cls, data):
        msg = super(MsgHubAction, cls).decode(data)
        assert isinstance(msg, MsgHubAction)
        msg.action = msg._byte()
        return msg


class MsgHubAlert(DownstreamMsg, UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#hub-alerts
    """
    TYPE = 0x03

    LOW_VOLTAGE = 0x01
    HIGH_CURRENT = 0x02
    LOW_SIGNAL = 0x03
    OVER_POWER = 0x04

    DESCR = {
        LOW_VOLTAGE: "low voltage",
        HIGH_CURRENT: "high current",
        LOW_SIGNAL: "low signal",
        OVER_POWER: "over power"
    }

    UPD_ENABLE = 0x01
    UPD_DISABLE = 0x02
    UPD_REQUEST = 0x03
    UPSTREAM_UPDATE = 0x04

    def __init__(self, atype=None, operation=None):
        super(MsgHubAlert, self).__init__()
        self.atype = atype
        self.operation = operation
        self.status = None

    def bytes(self):
        self.payload = pack("<B", self.atype) + pack("<B", self.operation)
        if self.operation == self.UPD_REQUEST:
            self.needs_reply = True
        return super(MsgHubAlert, self).bytes()

    @classmethod
    def decode(cls, data):
        msg = super(MsgHubAlert, cls).decode(data)
        assert isinstance(msg, MsgHubAlert)
        msg.atype = msg._byte()
        msg.operation = msg._byte()
        msg.status = msg._byte()

        assert(msg.operation == cls.UPSTREAM_UPDATE)
        return msg

    def is_ok(self):
        return not self.status

    def is_reply(self, msg):
        return isinstance(msg, MsgHubAlert) \
               and msg.operation == self.UPSTREAM_UPDATE and msg.atype == self.atype


class MsgHubAttachedIO(UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#hub-attached-i-o
    """
    TYPE = 0x04

    EVENT_DETACHED = 0x00
    EVENT_ATTACHED = 0x01
    EVENT_ATTACHED_VIRTUAL = 0x02

    # DEVICE TYPES
    DEV_UNKNOWN = 0x0000
    DEV_SIMPLE_MEDIUM_LINEAR_MOTOR = 0x0001 #Powered Up medium motor
    DEV_SYSTEM_TRAIN_MOTOR = 0x0002
    DEV_LED_LIGHT = 0x0008
    DEV_VOLTAGE = 0x0014
    DEV_CURRENT = 0x0015
    DEV_PIEZO_SOUND = 0x0016
    DEV_RGB_LIGHT = 0x0017 #HUB LED
    DEV_TILT = 0x0022
    DEV_MOTION_SENSOR = 0x0023
    DEV_VISION_SENSOR = 0x0025 #Color distance sensor
    DEV_MEDIUM_LINEAR_MOTOR = 0x0026 #Boost External motor
    DEV_MOVE_HUB_MEDIUM_LINEAR_MOTOR = 0x0027 #Move Hub medium linear motor
    DEV_MOVE_HUB_TILT = 0x0028 #Move Hub tilt sensor
    DEV_DUPLO_TRAIN_BASE_MOTOR = 0x0029
    DEV_DUPLO_TRAIN_BASE_SPEAKER = 0x002A
    DEV_DUPLO_TRAIN_BASE_COLOR_SENSOR = 0x002B
    DEV_DUPLO_TRAIN_BASE_SPEEDOMETER = 0x002C
    DEV_TECHNIC_LARGE_LINEAR_MOTOR = 0x002E #Technic Control+
    DEV_TECHNIC_XLARGE_LINEAR_MOTOR = 0x002F #Technic Control+
    DEV_TECHNIC_MEDIUM_ANGULAR_MOTOR = 0x0030 #Spike Prime
    DEV_TECHNIC_LARGE_ANGULAR_MOTOR = 0x0031 #Spike Prime
    DEV_TECHNIC_MEDIUM_HUB_GEST_SENSOR = 0x0036
    DEV_REMOTE_CONTROL_BUTTON = 0x0037
    DEV_REMOTE_CONTROL_RSSI = 0x0038
    DEV_TECHNIC_MEDIUM_HUB_ACCELEROMETER = 0x0039
    DEV_TECHNIC_MEDIUM_HUB_GYRO_SENSOR = 0x003A
    DEV_TECHNIC_MEDIUM_HUB_TILT_SENSOR = 0x003B
    DEV_TECHNIC_MEDIUM_HUB_TEMPERATURE_SENSOR = 0x003C
    DEV_TECHNIC_COLOR_SENSOR = 0x003D #Spike Prime
    DEV_TECHNIC_DISTANCE_SENSOR = 0x003E #Spike Prime
    DEV_TECHNIC_FORCE_SENSOR = 0x003F #Spike Prime

    def __init__(self):
        super(MsgHubAttachedIO, self).__init__()
        self.port = None
        self.event = None

    @classmethod
    def decode(cls, data):
        msg = super(MsgHubAttachedIO, cls).decode(data)
        assert isinstance(msg, MsgHubAttachedIO)
        msg.port = msg._byte()
        msg.event = msg._byte()
        return msg


class MsgGenericError(UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#generic-error-messages
    """
    TYPE = 0x05

    ERR_ACK = 0x01  # ACK
    ERR_MACK = 0x02  # MACK
    ERR_BUFFER_OVERFLOW = 0x03  # Buffer Overflow
    ERR_TIMEOUT = 0x04  # Timeout
    ERR_WRONG_COMMAND = 0x05  # Command NOT recognized
    ERR_WRONG_PARAMS = 0x06  # Invalid use (e.g. parameter error(s)
    ERR_OVERCURRENT = 0x07
    ERR_INTERNAL = 0x08

    DESCR = {
        ERR_ACK: "ACK",
        ERR_MACK: "MACK",
        ERR_BUFFER_OVERFLOW: "Buffer Overflow",
        ERR_TIMEOUT: "Timeout",
        ERR_WRONG_COMMAND: "Command NOT recognized",
        ERR_WRONG_PARAMS: "Invalid use (e.g. parameter error(s)",
        ERR_OVERCURRENT: "Overcurrent",
        ERR_INTERNAL: "Internal ERROR",
    }

    def __init__(self):
        super(MsgGenericError, self).__init__()
        self.cmd = None
        self.err = None

    @classmethod
    def decode(cls, data):
        msg = super(MsgGenericError, cls).decode(data)
        assert isinstance(msg, MsgGenericError)
        msg.cmd = msg._byte()
        msg.err = msg._byte()
        return msg

    def message(self):
        return "Command 0x%x caused error 0x%x: %s" % (self.cmd, self.err, self.DESCR[self.err])


class MsgPortInfoRequest(DownstreamMsg):
    """
    This is sync request for value on port
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-information-request
    """
    TYPE = 0x21

    INFO_PORT_VALUE = 0x00
    INFO_MODE_INFO = 0x01
    INFO_MODE_COMBINATIONS = 0x02

    def __init__(self, port, info_type):
        super(MsgPortInfoRequest, self).__init__()
        self.port = port
        self.info_type = info_type
        self.needs_reply = True

    def bytes(self):
        self.payload = pack("<B", self.port) + pack("<B", self.info_type)
        return super(MsgPortInfoRequest, self).bytes()

    def is_reply(self, msg):
        if self.info_type == self.INFO_PORT_VALUE:
            return isinstance(msg, (MsgPortValueSingle, MsgPortValueCombined)) and (msg.port == self.port)
        else:
            return isinstance(msg, (MsgPortInfo,)) and (msg.port == self.port)


class MsgPortModeInfoRequest(DownstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-mode-information-request
    """
    TYPE = 0x22

    INFO_NAME = 0x00
    INFO_RAW_RANGE = 0x01
    INFO_PCT_RANGE = 0x02
    INFO_SI_RANGE = 0x03  # no idea what 'SI' stands for
    INFO_UNITS = 0x04
    INFO_MAPPING = 0x05
    # INFO_INTERNAL = 0x06
    INFO_MOTOR_BIAS = 0x07
    INFO_CAPABILITY_BITS = 0x08
    INFO_VALUE_FORMAT = 0x80

    INFO_TYPES = {
        INFO_NAME: "Name",
        INFO_RAW_RANGE: "Raw range",
        INFO_PCT_RANGE: "Percent range",
        INFO_SI_RANGE: "SI value range",
        INFO_UNITS: "Units",
        INFO_MAPPING: "Mapping",
        INFO_MOTOR_BIAS: "Motor bias",
        INFO_CAPABILITY_BITS: "Capabilities",
        INFO_VALUE_FORMAT: "Value encoding",
    }

    def __init__(self, port, mode, info_type):
        super(MsgPortModeInfoRequest, self).__init__()
        self.port = port
        self.mode = mode
        self.info_type = info_type
        self.payload = pack("<B", port) + pack("<B", mode) + pack("<B", info_type)
        self.needs_reply = True

    def is_reply(self, msg):
        if not isinstance(msg, MsgPortModeInfo):
            return False

        if msg.port != self.port or msg.mode != self.mode or msg.info_type != self.info_type:
            return False

        return True


class MsgPortInputFmtSetupSingle(DownstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-input-format-setup-single
    """
    TYPE = 0x41

    def __init__(self, port, mode, delta=1, update_enable=0):
        super(MsgPortInputFmtSetupSingle, self).__init__()
        self.port = port
        self.mode = mode
        self.updates_enabled = update_enable
        self.update_delta = delta
        self.payload = pack("<B", port) + pack("<B", mode) + pack("<I", delta) + pack("<B", update_enable)
        self.needs_reply = True

    def is_reply(self, msg):
        if isinstance(msg, MsgPortInputFmtSingle) and msg.port == self.port:
            return True


class MsgPortInputFmtSetupCombined(DownstreamMsg): #TODO: Is this correct?
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-input-format-setup-combinedmode
    """
    TYPE = 0x42

    SC_SET_MODE_AND_DATASET = 0x01
    SC_LOCK_LPF2_DEVICE_FOR_SETUP = 0x02
    SC_UNLOCK_AND_START_WITH_MULTI_UPDATE_ENABLED = 0x03
    SC_UNLOCK_AND_START_WITH_MULTI_UPDATE_DISABLED = 0x04
    SC_RESET_SENSOR = 0x06 #Reset the sensor to the legacy mode 0

    def __init__(self, port, sub_cmd, combination_idx=None, mode=None, data_set=None):
        super(MsgPortInputFmtSetupCombined, self).__init__()
        self.port = port
        self.sub_cmd = sub_cmd
        self.combination_idx = combination_idx
        self.mode = mode
        self.data_set = data_set
        self.payload = pack("<B", port) + pack("<B", sub_cmd)
        if sub_cmd == self.SC_SET_MODE_AND_DATASET:
            self.payload += pack("<B", combination_idx) + pack("<B", mode * 16 + data_set)
        self.needs_reply = True

    def is_reply(self, msg):
        if isinstance(msg, MsgPortInputFmtCombined) and msg.port == self.port:
            return True


class MsgPortInfo(UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-information
    """
    TYPE = 0x43

    CAP_OUTPUT = 0b00000001
    CAP_INPUT = 0b00000010
    CAP_COMBINABLE = 0b00000100
    CAP_SYNCHRONIZABLE = 0b00001000

    def __init__(self):
        super(MsgPortInfo, self).__init__()
        self.port = None
        self.info_type = None
        self.capabilities = None
        self.total_modes = None
        self.input_modes = None
        self.output_modes = None
        self.possible_mode_combinations = []

    @classmethod
    def decode(cls, data):
        msg = super(MsgPortInfo, cls).decode(data)
        assert isinstance(msg, MsgPortInfo)
        msg.port = msg._byte()
        msg.info_type = msg._byte()
        if msg.info_type == MsgPortInfoRequest.INFO_MODE_INFO:
            msg.capabilities = msg._byte()
            msg.total_modes = msg._byte()
            msg.input_modes = msg._bits_list(msg._short())
            msg.output_modes = msg._bits_list(msg._short())
        else:
            while msg.payload:
                # https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#pos-m
                val = msg._short()
                msg.possible_mode_combinations.append(msg._bits_list(val))
                if not val:
                    break
        return msg

    def is_output(self):
        assert self.info_type == MsgPortInfoRequest.INFO_MODE_INFO
        return bool(self.capabilities & self.CAP_OUTPUT)

    def is_input(self):
        assert self.info_type == MsgPortInfoRequest.INFO_MODE_INFO
        return bool(self.capabilities & self.CAP_INPUT)

    def is_combinable(self):
        assert self.info_type == MsgPortInfoRequest.INFO_MODE_INFO
        return bool(self.capabilities & self.CAP_COMBINABLE)

    def is_synchronizable(self):
        assert self.info_type == MsgPortInfoRequest.INFO_MODE_INFO
        return bool(self.capabilities & self.CAP_SYNCHRONIZABLE)


class MsgPortModeInfo(UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-mode-information
    """
    TYPE = 0x44

    MAPPING_FLAGS = {
        7: "Supports NULL value",
        6: "Supports Functional Mapping 2.0+",
        5: "N/A",
        4: "Absolute [min..max]",
        3: "Relative [-1..1]",
        2: "Discrete [0, 1, 2, 3]",
        1: "N/A",
        0: "N/A",
    }

    DATASET_TYPES = {
        0b00: "8 bit",
        0b01: "16 bit",
        0b10: "32 bit",
        0b11: "FLOAT",
    }

    def __init__(self):
        super(MsgPortModeInfo, self).__init__()
        self.port = None
        self.mode = None
        self.info_type = None  # @see MsgPortModeInfoRequest
        self.value = None

    @classmethod
    def decode(cls, data):
        msg = super(MsgPortModeInfo, cls).decode(data)
        assert isinstance(msg, MsgPortModeInfo)
        msg.port = msg._byte()
        msg.mode = msg._byte()
        msg.info_type = msg._byte()
        msg.value = msg._value()
        return msg

    def _value(self):
        info = MsgPortModeInfoRequest
        if self.info_type == info.INFO_NAME:
            return self.payload[:self.payload.index(b"\00")].decode('ascii')
        elif self.info_type in (info.INFO_RAW_RANGE, info.INFO_PCT_RANGE, info.INFO_SI_RANGE):
            return [self._float(), self._float()]
        elif self.info_type == info.INFO_UNITS:
            return self.payload[:self.payload.index(b"\00")].decode('ascii')
        elif self.info_type == info.INFO_MAPPING:
            inp = self._bits_list(self._byte())
            outp = self._bits_list(self._byte())
            return {
                "input": [self.MAPPING_FLAGS[x] for x in inp],
                "output": [self.MAPPING_FLAGS[x] for x in outp],
            }
        elif self.info_type == info.INFO_MOTOR_BIAS:
            return self._byte()
        elif self.info_type == info.INFO_VALUE_FORMAT:
            return {
                "datasets": self._byte(),
                "type": self.DATASET_TYPES[self._byte()],
                "total_figures": self._byte(),
                "decimals": self._byte(),
            }
        else:
            return self.payload  # FIXME: will probably fail here


class MsgPortValueSingle(UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-value-single
    """
    TYPE = 0x45

    def __init__(self):
        super(MsgPortValueSingle, self).__init__()
        self.port = None

    @classmethod
    def decode(cls, data):
        msg = super(MsgPortValueSingle, cls).decode(data)
        assert isinstance(msg, MsgPortValueSingle)
        msg.port = msg._byte()
        return msg #msg[0] is the first value Byte


class MsgPortValueCombined(UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-value-combinedmode
    """
    TYPE = 0x46

    def __init__(self):
        super(MsgPortValueCombined, self).__init__()
        self.port = None
        self.configured_mode_datasets = None

    @classmethod
    def decode(cls, data):
        msg = super(MsgPortValueCombined, cls).decode(data)
        assert isinstance(msg, MsgPortValueCombined)
        msg.port = msg._byte()
        combined_bit_ptr = msg._short()
        msg.configured_mode_datasets = []
        for i in range(16):
            if combined_bit_ptr & (1 << i): 
                msg.configured_mode_datasets.append(i)
        return msg #msg[0] is the first value Byte


class MsgPortInputFmtSingle(UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-input-format-single
    """
    TYPE = 0x47

    def __init__(self, port=None, mode=None, upd_enabled=None, upd_delta=None):
        super(MsgPortInputFmtSingle, self).__init__()
        self.port = port
        self.mode = mode
        self.upd_delta = upd_delta
        self.upd_enabled = upd_enabled

    @classmethod
    def decode(cls, data):
        msg = super(MsgPortInputFmtSingle, cls).decode(data)
        assert isinstance(msg, MsgPortInputFmtSingle)
        msg.port = msg._byte()
        msg.mode = msg._byte()
        msg.upd_delta = msg._long()
        if len(msg.payload):
            msg.upd_enabled = msg._byte()

        return msg


class MsgPortInputFmtCombined(UpstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-input-format-combinedmode
    """
    TYPE = 0x48

    def __init__(self):
        super(MsgPortInputFmtCombined, self).__init__()
        self.port = None
        self.used_combination_idx = None
        self.multi_upd_enabled = None
        self.configured_mode_datasets = None

    @classmethod
    def decode(cls, data):
        msg = super(MsgPortInputFmtCombined, cls).decode(data)
        assert isinstance(msg, MsgPortInputFmtSingle)
        msg.port = msg._byte()
        combined_control = msg._byte()
        msg.used_combination_idx = 0x07 & combined_control
        msg.multi_upd_enabled = (0xE0 & combined_control) != 0
        combined_bit_ptr = msg._short()
        msg.configured_mode_datasets = []
        for i in range(16):
            if combined_bit_ptr & (1 << i): 
                msg.configured_mode_datasets.append(i)
        return msg


class MsgVirtualPortSetup(DownstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#virtual-port-setup
    """
    TYPE = 0x61

    CMD_DISCONNECT = 0x00
    CMD_CONNECT = 0x01

    def __init__(self, cmd, port):
        super(MsgVirtualPortSetup, self).__init__()
        self.payload = pack("<B", cmd)
        if cmd == self.CMD_DISCONNECT:
            assert isinstance(port, int)
            self.payload += pack("<B", port)
        else:
            assert isinstance(port, (list, tuple))
            self.payload += pack("<B", port[0]) + pack("<B", port[1])


class MsgPortOutput(DownstreamMsg):
    """
    https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#port-output-command
    """
    TYPE = 0x81

    SC_BUFFER_IF_NECESSARY = 0x00
    SC_NO_BUFFER = 0x10 #0b00000001
    SC_FEEDBACK = 0x01 #0b00010000

    WRITE_DIRECT = 0x50
    WRITE_DIRECT_MODE_DATA = 0x51

    def __init__(self, port, subcommand, params):
        super(MsgPortOutput, self).__init__()
        self.port = port
        self.is_buffered = False
        self.do_feedback = True
        self.subcommand = subcommand
        self.params = params

    def bytes(self):
        startup_completion_flags = 0
        if not self.is_buffered:
            startup_completion_flags |= self.SC_NO_BUFFER

        if self.do_feedback:
            startup_completion_flags |= self.SC_FEEDBACK
            self.needs_reply = True

        self.payload = pack("<B", self.port) + pack("<B", startup_completion_flags) \
                       + pack("<B", self.subcommand) + self.params
        return super(MsgPortOutput, self).bytes()

    def is_reply(self, msg):
        return isinstance(msg, MsgPortOutputFeedback) and msg.port == self.port \
               and (msg.is_completed() or self.is_buffered)


class MsgPortOutputFeedback(UpstreamMsg):
    TYPE = 0x82

    FBK_BUFFER_EMPTY_CMD_IN_PROGRESS = 0x01
    FBK_BUFFER_EMPTY_CMD_COMPLETED = 0x02
    FBK_CMD_DISCARDED = 0x04
    FBK_IDLE = 0x08
    FBK_BUSY_FULL = 0x10

    def __init__(self):
        super(MsgPortOutputFeedback, self).__init__()
        self.port = None
        self.status = None
        self.is_multi_port = None

    @classmethod
    def decode(cls, data):
        msg = super(MsgPortOutputFeedback, cls).decode(data)
        assert isinstance(msg, MsgPortOutputFeedback)
        assert(len(msg.payload) % 2 == 0)
        msg.is_multi_port = len(msg.payload) > 2
        if msg.is_multi_port:
            msg.port = []
            msg.status = []
            for i in range(len(msg.payload) / 2):
                msg.port.append(msg._byte())
                msg.status.append(msg._byte())
        else:
            msg.port = msg._byte()
            msg.status = msg._byte()
        return msg

    def is_in_progress(self):
        return self.status & 0b0001

    def is_completed(self):
        return self.status & 0b0010

    def is_discarded(self):
        return self.status & 0b0100

    def is_idle(self):
        return self.status & 0b1000

#-------------------------------------------------------------------------

UPSTREAM_MSGS = (
    MsgHubProperties, MsgHubAction, MsgHubAlert, MsgHubAttachedIO, MsgGenericError,
    MsgPortInfo, MsgPortModeInfo,
    MsgPortValueSingle, MsgPortValueCombined, MsgPortInputFmtSingle, MsgPortInputFmtCombined,
    MsgPortOutputFeedback
)

#-------------------------------------------------------------------------