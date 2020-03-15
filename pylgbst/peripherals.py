import logging
import math
import traceback
from struct import pack, unpack
from threading import Thread

from pylgbst.messages import MsgHubProperties, MsgHubAttachedIO, MsgPortOutput, MsgPortInputFmtSetupSingle, MsgPortInfoRequest, MsgPortModeInfoRequest, MsgPortInfo, MsgPortModeInfo, MsgPortInputFmtSingle
from pylgbst.utilities import queue, str2hex, usbyte, ushort, usint, sbyte, sshort, sint, sfloat, sdouble
from pylgbst.hub import HubType

#-------------------------------------------------------------------------

log = logging.getLogger('peripherals')

#-------------------------------------------------------------------------

PERIPHERAL_NAMES = {
    MsgHubAttachedIO.DEV_UNKNOWN: "Unknown",
    MsgHubAttachedIO.DEV_SIMOLE_MEDIUM_LINEAR_MOTOR: "Simple Medium Linear Motor",
    MsgHubAttachedIO.DEV_SYSTEM_TRAIN_MOTOR: "System Train Motor",
    MsgHubAttachedIO.DEV_LED_LIGHT: "LED Light",
    MsgHubAttachedIO.DEV_VOLTAGE: "Voltage Sensor",
    MsgHubAttachedIO.DEV_CURRENT: "Current Sensor",
    MsgHubAttachedIO.DEV_PIEZO_SOUND: "Piezo Sound",
    MsgHubAttachedIO.DEV_RGB_LIGHT: "Hub LED", #HUB LED
    MsgHubAttachedIO.DEV_TILT: "Tilt Sensor",
    MsgHubAttachedIO.DEV_MOTION_SENSOR: "Motion Seneor",
    MsgHubAttachedIO.DEV_VISION_SENSOR: "Vision Sensor", #Color distance senesor
    MsgHubAttachedIO.DEV_MEDIUM_LINEAR_MOTOR: "Medium Linear Motor",
    MsgHubAttachedIO.DEV_MOVE_HUB_MEDIUM_LINEAR_MOTOR: "Move Hub Medium Linear Motor", #Move Hub medium linear motor
    MsgHubAttachedIO.DEV_MOVE_HUB_TILT: "Move Hub Tilt Sensor", #Move Hub tilt sensor
    MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_MOTOR: "Duplo Train Base Motor",
    MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_SPEAKER: "Duplo Train Base Speaker",
    MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_COLOR_SENSOR: "Duplo Train Base Color Sensor",
    MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_SPEEDOMETER: "Duplo Train Base Speedometer",
    MsgHubAttachedIO.DEV_TECHNIC_LARGE_LINEAR_MOTOR: "Technic Large Linear Motor", #Technic Control+
    MsgHubAttachedIO.DEV_TECHNIC_XLARGE_LINEAR_MOTOR: "Technic XLarge Linear Motor", #Technic Control+
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_ANGULAR_MOTOR: "Technic Medium Angular Motor", #Spike Prime
    MsgHubAttachedIO.DEV_TECHNIC_LARGE_ANGULAR_MOTOR: "Technic Large Angular Motor", #Spike Prime
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_GEST_SENSOR: "Technic Medium Gest Sensor",
    MsgHubAttachedIO.DEV_REMOTE_CONTROL_BUTTON: "Remote Control Button",
    MsgHubAttachedIO.DEV_REMOTE_CONTROL_RSSI: "Remote Control RSSI",
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_ACCELEROMETER: "Technic Hub Accelerometer",
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_GYRO_SENSOR: "Technic Hub Gyro Sensor",
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_TILT_SENSOR: "Technic Hub Tilt Sensor",
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_TEMPERATURE_SENSOR: "Technic Hub Temperature Sensor",
    MsgHubAttachedIO.DEV_TECHNIC_COLOR_SENSOR: "Spike Prime Hub Color Sensor", #Spike Prime
    MsgHubAttachedIO.DEV_TECHNIC_DISTANCE_SENSOR: "Spike Prime Hub Distance Sensor", #Spike Prime
    MsgHubAttachedIO.DEV_TECHNIC_FORCE_SENSOR: "Spike Prime Hub Force Sensor" #Spike Prime
}

# COLORS
COLOR_BLACK = 0x00
COLOR_PINK = 0x01
COLOR_PURPLE = 0x02
COLOR_BLUE = 0x03
COLOR_LIGHTBLUE = 0x04
COLOR_CYAN = 0x05
COLOR_GREEN = 0x06
COLOR_YELLOW = 0x07
COLOR_ORANGE = 0x08
COLOR_RED = 0x09
COLOR_WHITE = 0x0a
COLOR_NONE = 0xFF

COLORS = {
    COLOR_BLACK: "BLACK",
    COLOR_PINK: "PINK",
    COLOR_PURPLE: "PURPLE",
    COLOR_BLUE: "BLUE",
    COLOR_LIGHTBLUE: "LIGHTBLUE",
    COLOR_CYAN: "CYAN",
    COLOR_GREEN: "GREEN",
    COLOR_YELLOW: "YELLOW",
    COLOR_ORANGE: "ORANGE",
    COLOR_RED: "RED",
    COLOR_WHITE: "WHITE",
    COLOR_NONE: "NONE"
}

#-------------------------------------------------------------------------

# TODO: support more types of peripherals from
# https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#io-type-id

class Peripheral(object):
    """
    :type parent: pylgbst.hub.Hub
    :type _incoming_port_data: queue.Queue
    :type _port_mode: MsgPortInputFmtSingle
    """

    def __init__(self, parent, port):
        """
        :type parent: pylgbst.hub.Hub
        :type port: int
        """
        super(Peripheral, self).__init__()
        self.virtual_ports = ()
        self.hub = parent
        self.port = port
        self.type = MsgHubAttachedIO.DEV_UNKNOWN

        self.is_buffered = False

        self._subscribers = set()
        self._port_mode = MsgPortInputFmtSingle(self.port, None, False, 1)

        self._incoming_port_data = queue.Queue(1)  # limit 1 means we drop data if we can't handle it fast enough
        thr = Thread(target=self._queue_reader)
        thr.setDaemon(True)
        thr.setName("Port data queue: %s" % self)
        thr.start()

    def __repr__(self):
        msg = "%s on port 0x%x" % (self.__class__.__name__, self.port if self.port is not None else -1)
        if self.virtual_ports:
            msg += " (ports 0x%x and 0x%x combined)" % (self.virtual_ports[0], self.virtual_ports[1])
        return msg
        
    def is_port_virtual(self):
        return not (not self.virtual_ports)

    def set_port_mode(self, mode, send_updates=None, update_delta=None):
        assert not self.virtual_ports, "TODO: support combined mode for sensors" #TODO: support combined mode

        if send_updates is None:
            send_updates = self._port_mode.upd_enabled
            log.debug("Implied update is enabled=%s", send_updates)

        if update_delta is None:
            update_delta = self._port_mode.upd_delta
            log.debug("Implied update delta=%s", update_delta)

        if self._port_mode.mode == mode \
                and self._port_mode.upd_enabled == send_updates \
                and self._port_mode.upd_delta == update_delta:
            log.debug("Already in target mode, no need to switch")
            return
        else:
            msg = MsgPortInputFmtSetupSingle(self.port, mode, update_delta, send_updates)
            resp = self.hub.send(msg)
            assert isinstance(resp, MsgPortInputFmtSingle)
            self._port_mode = resp

    def _send_output(self, msg):
        assert isinstance(msg, MsgPortOutput)
        msg.is_buffered = self.is_buffered  # TODO: support buffering
        self.hub.send(msg)

    def get_sensor_data(self, mode=None):
        if mode is not None:
            self.set_port_mode(mode)
        msg = MsgPortInfoRequest(self.port, MsgPortInfoRequest.INFO_PORT_VALUE)
        resp = self.hub.send(msg)
        return self._decode_port_data(resp)

    def subscribe(self, callback, mode=0x00, update_delta=1):
        if self._port_mode.mode != mode and self._subscribers:
            raise ValueError("Port is in active mode %r, unsubscribe all subscribers first" % self._port_mode)
        self.set_port_mode(mode, True, update_delta)
        if callback:
            self._subscribers.add(callback)

    def unsubscribe(self, callback=None):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

        if not self._port_mode.upd_enabled:
            log.warning("Attempt to unsubscribe while port value updates are off: %s", self)
        elif not self._subscribers:
            self.set_port_mode(self._port_mode.mode, False)

    def _notify_subscribers(self, *args, **kwargs):
        for subscriber in self._subscribers.copy():
            subscriber(*args, **kwargs)
        return args

    def queue_port_data(self, msg):
        try:
            self._incoming_port_data.put_nowait(msg)
        except queue.Full:
            log.debug("Dropped port data: %r", msg)

    def _decode_port_data(self, msg):
        """
        :rtype: tuple
        """
        log.warning("Unhandled port data: %r", msg)
        return ()

    def _handle_port_data(self, msg):
        """
        :type msg: pylgbst.messages.MsgPortValueSingle
        """
        decoded = self._decode_port_data(msg)
        assert isinstance(decoded, (tuple, list)), "Unexpected data type: %s" % type(decoded)
        self._notify_subscribers(*decoded)

    def _queue_reader(self):
        while True:
            msg = self._incoming_port_data.get()
            try:
                self._handle_port_data(msg)
            except BaseException:
                log.warning("%s", traceback.format_exc())
                log.warning("Failed to handle port data by %s: %r", self, msg)

    def describe_possible_modes(self):
        mode_info = self.hub.send(MsgPortInfoRequest(self.port, MsgPortInfoRequest.INFO_MODE_INFO))
        assert isinstance(mode_info, MsgPortInfo)
        info = {
            "mode_count": mode_info.total_modes,
            "input_modes": [],
            "output_modes": [],
            "capabilities": {
                "logically_combinable": mode_info.is_combinable(),
                "synchronizable": mode_info.is_synchronizable(),
                "can_output": mode_info.is_output(),
                "can_input": mode_info.is_input(),
            }
        }

        if mode_info.is_combinable():
            mode_combinations = self.hub.send(MsgPortInfoRequest(self.port, MsgPortInfoRequest.INFO_MODE_COMBINATIONS))
            assert isinstance(mode_combinations, MsgPortInfo)
            info['possible_mode_combinations'] = mode_combinations.possible_mode_combinations

        info['modes'] = []
        for mode in range(256):
            info['modes'].append(self._describe_mode(mode))

        for mode in mode_info.output_modes:
            info['output_modes'].append(self._describe_mode(mode))

        for mode in mode_info.input_modes:
            info['input_modes'].append(self._describe_mode(mode))

        log.debug("Port info for 0x%x: %s", self.port, info)
        return info

    def _describe_mode(self, mode):
        descr = {"Mode": mode}
        for info in MsgPortModeInfoRequest.INFO_TYPES:
            try:
                resp = self.hub.send(MsgPortModeInfoRequest(self.port, mode, info))
                assert isinstance(resp, MsgPortModeInfo)
                descr[MsgPortModeInfoRequest.INFO_TYPES[info]] = resp.value
            except RuntimeError:
                log.debug("Got error while requesting info 0x%x: %s", info, traceback.format_exc())
                if info == MsgPortModeInfoRequest.INFO_NAME:
                    break
        return descr

class LEDLight(Peripheral):
    MODE_BRIGHTNESS = 0x00

    def __init__(self, parent, port):
        super(LEDLight, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_LED_LIGHT

    def set_brightness(self, brightness):
        self.set_port_mode(self.MODE_BRIGHTNESS)
        payload = pack("<B", self.MODE_BRIGHTNESS) + pack("<B", brightness)

        msg = MsgPortOutput(self.port, MsgPortOutput.WRITE_DIRECT_MODE_DATA, payload)
        self._send_output(msg)


class LEDRGB(Peripheral):
    MODE_INDEX = 0x00
    MODE_RGB = 0x01

    def __init__(self, parent, port):
        super(LEDRGB, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_RGB_LIGHT

    def set_color(self, color):
        if isinstance(color, (list, tuple)):
            assert len(color) == 3, "RGB color has to have 3 values"
            self.set_port_mode(self.MODE_RGB)
            payload = pack("<B", self.MODE_RGB) + pack("<B", color[0]) + pack("<B", color[1]) + pack("<B", color[2])
        else:
            if color == COLOR_NONE:
                color = COLOR_BLACK

            if color not in COLORS:
                raise ValueError("Color %s is not in list of available colors" % color)

            self.set_port_mode(self.MODE_INDEX)
            payload = pack("<B", self.MODE_INDEX) + pack("<B", color)

        msg = MsgPortOutput(self.port, MsgPortOutput.WRITE_DIRECT_MODE_DATA, payload)
        self._send_output(msg)

    def _decode_port_data(self, msg):
        if len(msg.payload) == 3:
            return usbyte(msg.payload, 0), usbyte(msg.payload, 1), usbyte(msg.payload, 2),
        else:
            return usbyte(msg.payload, 0),


class BasicMotor(Peripheral):
    SUBCMD_START_POWER = 0x00
    SUBCMD_START_POWER_GROUPED = 0x03

    END_STATE_BRAKE = 127
    END_STATE_HOLD = 126
    END_STATE_FLOAT = 0

    def __init__(self, parent, port):
        super(BasicMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_UNKNOWN

    def _map_speed(self, speed):
        if speed == BasicMotor.END_STATE_BRAKE or speed == BasicMotor.END_STATE_HOLD:
            # special value for BRAKE https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-startpower-power
            return speed

        if speed < -100:
            log.warning("Speed cannot be less than -100")
            speed = -100

        if speed > 100:
            log.warning("Speed cannot be more than 100")
            speed = 100

        return speed

    def _write_direct_mode(self, subcmd, params):
        params = pack("<B", subcmd) + params
        msg = MsgPortOutput(self.port, MsgPortOutput.WRITE_DIRECT_MODE_DATA, params)
        self._send_output(msg)

    def _send_cmd(self, subcmd, params):
        if self.virtual_ports:
            subcmd += 1  # de-facto rule

        msg = MsgPortOutput(self.port, subcmd, params)
        self._send_output(msg)

    def set_power(self, power_primary=100, power_secondary=None):
        """
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-startpower-power
        Set the motor(s) power.
        :type power_primary: int [0-100] or [-1--100] for reverse or 0 for stop or 127 for break.
        """
        if self.virtual_ports and power_secondary is None: 
            power_secondary = power_primary

        if power_secondary is None:
            subcmd = self.SUBCMD_START_POWER
        else:
            subcmd = self.SUBCMD_START_POWER_GROUPED

        params = b""
        params += pack("<b", self._map_speed(power_primary))
        if power_secondary is not None:
            params += pack("<b", self._map_speed(power_secondary))

        self._write_direct_mode(subcmd, params)

    def stop(self):
        self.set_power(0)

    def break_motor(self):
        self.set_power(BasicMotor.END_STATE_BRAKE)

class TachoMotor(BasicMotor):
    SUBCMD_SET_ACC_TIME = 0x05
    SUBCMD_SET_DEC_TIME = 0x06
    SUBCMD_START_SPEED = 0x07
    SUBCMD_START_SPEED2 = 0x08
    SUBCMD_START_SPEED_FOR_TIME = 0x09
    SUBCMD_START_SPEED_FOR_TIME2 = 0x0A
    SUBCMD_START_SPEED_FOR_DEGREES = 0x0B
    SUBCMD_START_SPEED_FOR_DEGREES2 = 0x0C

    SENSOR_POWER = 0x00  # it's not input mode, hovewer returns some numbers
    SENSOR_SPEED = 0x01
    SENSOR_ANGLE = 0x02

    def __init__(self, parent, port):
        super(TachoMotor, self).__init__(parent, port)    

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.SENSOR_ANGLE:
            angle = sint(data, 0)
            return (angle,)
        elif self._port_mode.mode == self.SENSOR_SPEED:
            speed = sbyte(data, 0)
            return (speed,)
        else:
            log.debug("Got motor sensor data while in unexpected mode: %r", self._port_mode)
            return ()

    def set_acc_profile(self, seconds, profile_no=0x00):
        """
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-setacctime-time-profileno-0x05
        Set acceleration profile for the motor.
        :type seconds: int/float; time for acceleration from 0 to 100 (in seconds)
        """
        params = b""
        params += pack("<H", int(seconds * 1000))
        params += pack("<B", profile_no)

        self._send_cmd(self.SUBCMD_SET_ACC_TIME, params)

    def set_dec_profile(self, seconds, profile_no=0x00):
        """
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-setdectime-time-profileno-0x06
        Set deceleration profile for the motor.
        :type seconds: int/float; time for deceleration from 100 to 0 (in seconds)
        """
        params = b""
        params += pack("<H", int(seconds * 1000))
        params += pack("<B", profile_no)

        self._send_cmd(self.SUBCMD_SET_DEC_TIME, params)

    def set_speed(self, speed_primary=100, speed_secondary=None, max_power=100, use_profile=0b11):
        """
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-startspeed-speed-maxpower-useprofile-0x07
        Start or hold motor(s) and keep the speed/position without exceeding power-levels > max_power.
        Run motor(s) for given time.
        :type speed_primary: int [0-100]
        :type max_power: int [0-100]
        """
        if self.virtual_ports and speed_secondary is None: 
            speed_secondary = speed_primary

        if speed_secondary is None:
            subcmd = self.SUBCMD_START_SPEED
        else:
            subcmd = self.SUBCMD_START_SPEED2

        params = b""
        params += pack("<b", self._map_speed(speed_primary))
        if speed_secondary is not None:
            params += pack("<b", self._map_speed(speed_secondary))

        params += pack("<B", max_power)
        params += pack("<B", use_profile)

        self._send_cmd(subcmd, params)

    def set_time(self, seconds, speed_primary=100, speed_secondary=None, max_power=100, end_state=BasicMotor.END_STATE_BRAKE, use_profile=0b11):
        """
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-startspeedfortime-time-speed-maxpower-endstate-useprofile-0x09
        Run motor(s) for given time.
        :type seconds: int/float (in seconds)
        :type speed_primary: int [0-100]
        :type max_power: int [0-100]
        """
        if self.virtual_ports and speed_secondary is None: 
                speed_secondary = speed_primary

        if speed_secondary is None:
            subcmd = self.SUBCMD_START_SPEED_FOR_TIME
        else:
            subcmd = self.SUBCMD_START_SPEED_FOR_TIME2

        params = b""
        params += pack("<H", int(seconds * 1000))
        params += pack("<b", self._map_speed(speed_primary))
        if speed_secondary is not None:
            params += pack("<b", self._map_speed(speed_secondary))

        params += pack("<B", max_power)
        params += pack("<B", end_state)
        params += pack("<B", use_profile)

        self._send_cmd(subcmd, params)

    def rotate_by_angle(self, degrees, speed_primary=100, speed_secondary=None, max_power=100, end_state=BasicMotor.END_STATE_BRAKE, use_profile=0b11):
        """
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-startspeedfordegrees-degrees-speed-maxpower-endstate-useprofile-0x0b
        Rotate a motor by a given amount of degrees.
        :type degrees: int (in degrees)
        :type speed_primary: int [0-100]
        :type max_power: int [0-100]
        """
        if self.virtual_ports and speed_secondary is None: 
            speed_secondary = speed_primary

        if speed_secondary is None:
            subcmd = self.SUBCMD_START_SPEED_FOR_DEGREES
        else:
            subcmd = self.SUBCMD_START_SPEED_FOR_DEGREES2

        degrees = int(round(degrees))
        if degrees < 0:
            degrees = -degrees
            speed_primary = -speed_primary
            if speed_secondary is not None:
                speed_secondary = -speed_secondary

        params = b""
        params += pack("<I", degrees)
        params += pack("<b", self._map_speed(speed_primary))
        if speed_secondary is not None:
            params += pack("<b", self._map_speed(speed_secondary))

        params += pack("<B", max_power)
        params += pack("<B", end_state)
        params += pack("<B", use_profile)

        self._send_cmd(subcmd, params)

    def stop(self):
        self.set_time(0)

class AbsMotor(TachoMotor):
    SUBCMD_GOTO_ABSOLUTE_POSITION = 0x0D
    SUBCMD_GOTO_ABSOLUTE_POSITION2 = 0x0E
    SUBCMD_PRESET_ENCODER = 0x14

    SENSOR_ABSOLUTE = 0x03

    def __init__(self, parent, port):
        super(AbsMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_UNKNOWN

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.SENSOR_ABSOLUTE:
            angle_position = sshort(data, 0)
            return (angle_position,)
        else:
            return super(AbsMotor, self)._decode_port_data(msg)

    @staticmethod
    def _normalize_angle(angle):
        if angle >= 180:
            return angle - (360 * ((angle + 180) / 360))
        elif angle < -180:
            return angle + (360 * ((180 - angle) / 360))
        return angle

    @staticmethod
    def _round_to_neares_90(angle):
        angle = AbsMotor._normalize_angle(angle)
        if angle < -135:
            return -180
        if angle < -45:
            return -90
        if angle < 45:
            return 0
        if angle < 135:
            return 90
        return -180

    def subscribe(self, callback, mode=SENSOR_ABSOLUTE, update_delta=1):
        super(AbsMotor, self).subscribe(callback, mode, update_delta)

    def goto_abs_position(self, degrees_primary, degrees_secondary=None, speed=100, max_power=100, end_state=BasicMotor.END_STATE_BRAKE, use_profile=0b11):
        """
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-gotoabsoluteposition-abspos-speed-maxpower-endstate-useprofile-0x0d
        Rotate a motor(s) to a given position (angle).
        :type degrees_primary: int (in degrees)
        :type speed: int [0-100]
        :type max_power: int [0-100]
        """
        if self.virtual_ports and degrees_secondary is None: 
            degrees_secondary = degrees_primary

        if degrees_secondary is None:
            subcmd = self.SUBCMD_GOTO_ABSOLUTE_POSITION
        else:
            subcmd = self.SUBCMD_GOTO_ABSOLUTE_POSITION2

        params = b""
        params += pack("<i", AbsMotor._normalize_angle(degrees_primary))
        if degrees_secondary is not None:
            params += pack("<i", AbsMotor._normalize_angle(degrees_secondary))

        params += pack("<b", self._map_speed(speed))

        params += pack("<B", max_power)
        params += pack("<B", end_state)
        params += pack("<B", use_profile)

        self._send_cmd(subcmd, params)

    def preset_encoder(self, degrees=0, degrees_secondary=None, only_individual=True):
        """
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-presetencoder-position-n-a
        https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-presetencoder-leftposition-rightposition-0x14
        Preset the encoder of the motor(s) to position.
        :type degrees: int (in degrees) or 0 for reset
        :type only_individual: bool; if True only the individual encoders of the synchronized motors are preset and the synchronized virtual encoders are not affected
        """
        if self.virtual_ports and degrees_secondary is None:
            degrees_secondary = degrees

        if only_individual and degrees_secondary is not None:
            self._send_cmd(self.SUBCMD_PRESET_ENCODER, pack("<i", degrees) + pack("<i", degrees_secondary))
        else:
            params = pack("<i", degrees)
            self._write_direct_mode(self.SENSOR_ANGLE, params)


class SimpleMediumLinearMotor(BasicMotor):
    def __init__(self, parent, port):
        super(SimpleMediumLinearMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_SIMOLE_MEDIUM_LINEAR_MOTOR

class SystemTrainMotor(BasicMotor):
    def __init__(self, parent, port):
        super(SystemTrainMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_SYSTEM_TRAIN_MOTOR

class DuploTrainBaseMotor(BasicMotor):
    def __init__(self, parent, port):
        super(DuploTrainBaseMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_MOTOR       

class MediumLinearMotor(TachoMotor):
    def __init__(self, parent, port):
        super(MediumLinearMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_MEDIUM_LINEAR_MOTOR

class MoveHubMediumLinearMotor(TachoMotor):
    def __init__(self, parent, port):
        super(MoveHubMediumLinearMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_MOVE_HUB_MEDIUM_LINEAR_MOTOR

class TechnicMediumAngularMotor(AbsMotor):
    def __init__(self, parent, port):
        super(TechnicMediumAngularMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_ANGULAR_MOTOR

class TechnicLargeAngularMotor(AbsMotor):
    def __init__(self, parent, port):
        super(TechnicLargeAngularMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_LARGE_ANGULAR_MOTOR

class TechnicLargeLinearMotor(AbsMotor):
    def __init__(self, parent, port):
        super(TechnicLargeLinearMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_LARGE_LINEAR_MOTOR

class TechnicXLargeLinearMotor(AbsMotor):
    def __init__(self, parent, port):
        super(TechnicXLargeLinearMotor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_XLARGE_LINEAR_MOTOR


class TechnicHubAccelerometerSensor(Peripheral):

    MODE_ACCEL = 0x00

    def __init__(self, parent, port):
        super(TechnicHubAccelerometerSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_ACCELEROMETER

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_ACCEL:
            #Unit: mG
            x = round(sshort(data, 0) / 4.096)
            y = round(sshort(data, 2) / 4.096)
            z = round(sshort(data, 4) / 4.096)
            return (x,y,z)
        else:
            log.debug("Got Technic hub accelerometer sensor data while in unexpected mode: %r", self._port_mode)
            return ()


class TechnicHubGyroSensor(Peripheral):

    MODE_GYRO = 0x00

    def __init__(self, parent, port):
        super(TechnicHubGyroSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_GYRO_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_GYRO:
            #Unit: DPS (degrees per second)
            x = round(sshort(data, 0) * 7 / 400)
            y = round(sshort(data, 2) * 7 / 400)
            z = round(sshort(data, 4) * 7 / 400)
            return (x,y,z)
        else:
            log.debug("Got Technic hub gyro sensor data while in unexpected mode: %r", self._port_mode)
            return ()


class TechnicHubTiltSensor(Peripheral):

    MODE_TILT = 0x00

    def __init__(self, parent, port):
        super(TechnicHubTiltSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_TILT_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_TILT:
            #Unit: 
            x = -sshort(data, 0)
            y = sshort(data, 2)
            z = sshort(data, 4)
            return (x,y,z)
        else:
            log.debug("Got Technic hub tilt sensor data while in unexpected mode: %r", self._port_mode)
            return ()


class GenericTiltSensor(Peripheral):
    MODE_2AXIS_ANGLE = 0x00
    MODE_2AXIS_SIMPLE = 0x01
    MODE_3AXIS_SIMPLE = 0x02
    MODE_IMPACT_COUNT = 0x03
    MODE_3AXIS_ACCEL = 0x04
    MODE_ORIENT_CF = 0x05
    MODE_IMPACT_CF = 0x06
    MODE_CALIBRATION = 0x07

    TRI_BACK = 0x00
    TRI_UP = 0x01
    TRI_DOWN = 0x02
    TRI_LEFT = 0x03
    TRI_RIGHT = 0x04
    TRI_FRONT = 0x05

    DUO_HORIZ = 0x00
    DUO_DOWN = 0x03
    DUO_LEFT = 0x05
    DUO_RIGHT = 0x07
    DUO_UP = 0x09

    DUO_STATES = {
        DUO_HORIZ: "HORIZONTAL",
        DUO_DOWN: "DOWN",
        DUO_LEFT: "LEFT",
        DUO_RIGHT: "RIGHT",
        DUO_UP: "UP",
    }

    TRI_STATES = {
        TRI_BACK: "BACK",
        TRI_UP: "UP",
        TRI_DOWN: "DOWN",
        TRI_LEFT: "LEFT",
        TRI_RIGHT: "RIGHT",
        TRI_FRONT: "FRONT",
    }

    def __init__(self, parent, port):
        super(GenericTiltSensor, self).__init__(parent, port)

    def subscribe(self, callback, mode=MODE_3AXIS_SIMPLE, update_delta=1):
        super(GenericTiltSensor, self).subscribe(callback, mode, update_delta)

    def _decode_port_data(self, msg):
        #TODO: Is this correct?
        data = msg.payload
        if self._port_mode.mode == self.MODE_2AXIS_ANGLE:
            roll = sbyte(data, 0)
            pitch = sbyte(data, 1)
            return (roll, pitch)
        elif self._port_mode.mode == self.MODE_3AXIS_SIMPLE:
            state = usbyte(data, 0)
            return (state,)
        elif self._port_mode.mode == self.MODE_2AXIS_SIMPLE:
            state = usbyte(data, 0)
            return (state,)
        elif self._port_mode.mode == self.MODE_IMPACT_COUNT:
            bump_count = usint(data, 0)
            return (bump_count,)
        elif self._port_mode.mode == self.MODE_3AXIS_ACCEL:
            roll = sbyte(data, 0)
            pitch = sbyte(data, 1)
            yaw = sbyte(data, 2)  # did I get the order right?
            return (roll, pitch, yaw)
        elif self._port_mode.mode == self.MODE_ORIENT_CF:
            state = usbyte(data, 0)
            return (state,)
        elif self._port_mode.mode == self.MODE_IMPACT_CF:
            state = usbyte(data, 0)
            return (state,)
        elif self._port_mode.mode == self.MODE_CALIBRATION:
            return (usbyte(data, 0), usbyte(data, 1), usbyte(data, 2))
        else:
            log.debug("Unsupported tilt sensor mode: %r", self._port_mode)
            return ()

    # TODO: add some methods from official doc, like
    # https://lego.github.io/lego-ble-wireless-protocol-docs/index.html#output-sub-command-tiltconfigimpact-impactthreshold-bumpholdoff-n-a

class TiltSensor(GenericTiltSensor):
    def __init__(self, parent, port):
        super(TiltSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TILT

class MoveHubTiltSensor(GenericTiltSensor):
    def __init__(self, parent, port):
        super(MoveHubTiltSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_MOVE_HUB_TILT

class VisionSensor(Peripheral):
    COLOR_INDEX = 0x00
    DISTANCE_INCHES = 0x01
    COUNT_2INCH = 0x02
    DISTANCE_REFLECTED = 0x03
    AMBIENT_LIGHT = 0x04
    SET_COLOR = 0x05
    COLOR_RGB = 0x06
    SET_IR_TX = 0x07
    COLOR_DISTANCE_FLOAT = 0x08  # it's not declared by dev's mode info

    DEBUG = 0x09  # first val is by fact ambient light, second is zero
    CALIBRATE = 0x0a  # gives constant values

    def __init__(self, parent, port):
        super(VisionSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_VISION_SENSOR

    def subscribe(self, callback, mode=COLOR_DISTANCE_FLOAT, update_delta=1):
        super(VisionSensor, self).subscribe(callback, mode, update_delta)

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.COLOR_INDEX:
            color = usbyte(data, 0)
            return (color,)
        elif self._port_mode.mode == self.DISTANCE_INCHES:
            distance = usbyte(data, 0)
            return (distance,)
        elif self._port_mode.mode == self.COLOR_DISTANCE_FLOAT:
            color = usbyte(data, 0)
            distance = usbyte(data, 1)
            partial = usbyte(data, 3)
            if partial:
                distance = float(distance) + 1.0 / partial
            #distance = math.floor(distance * 25.4) - 20 #TODO: check if correct
            return (color, distance)
        elif self._port_mode.mode == self.DISTANCE_REFLECTED:
            distance = usbyte(data, 0) / 100.0
            return (distance,)
        elif self._port_mode.mode == self.AMBIENT_LIGHT:
            val = usbyte(data, 0) / 100.0
            return (val,)
        elif self._port_mode.mode == self.COUNT_2INCH:
            count = usint(data, 0)
            return (count,)
        elif self._port_mode.mode == self.COLOR_RGB:
            val1 = int(255 * ushort(data, 0) / 1023.0)
            val2 = int(255 * ushort(data, 2) / 1023.0)
            val3 = int(255 * ushort(data, 4) / 1023.0)
            return (val1, val2, val3)
        elif self._port_mode.mode == self.DEBUG:
            val1 = 10 * ushort(data, 0) / 1023.0
            val2 = 10 * ushort(data, 2) / 1023.0
            return (val1, val2)
        elif self._port_mode.mode == self.CALIBRATE:
            return [ushort(data, x * 2) for x in range(8)]
        else:
            log.debug("Unsupported VisionSensor mode %s with data: %s", self._port_mode.mode, str2hex(data))
            return ()

    def set_color(self, color):
        if color == COLOR_NONE:
            color = COLOR_BLACK

        if color not in COLORS:
            raise ValueError("Color %s is not in list of available colors" % color)

        self.set_port_mode(self.SET_COLOR)
        payload = pack("<B", self.SET_COLOR) + pack("<B", color)

        msg = MsgPortOutput(self.port, MsgPortOutput.WRITE_DIRECT_MODE_DATA, payload)
        self._send_output(msg)

    def set_ir_tx(self, level=1.0):
        assert 0 <= level <= 1.0
        self.set_port_mode(self.SET_IR_TX)
        payload = pack("<B", self.SET_IR_TX) + pack("<H", int(level * 65535))

        msg = MsgPortOutput(self.port, MsgPortOutput.WRITE_DIRECT_MODE_DATA, payload)
        self._send_output(msg)


class DuploTrainColorSensor(Peripheral):

    MODE_COLOR = 0x00
    MODE_REFLECTIVITY = 0x02
    MODE_RGB = 0x03

    def __init__(self, parent, port):
        super(DuploTrainColorSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_COLOR_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_COLOR:
            #Emits when color sensor is activated
            color = usbyte(data, 0)
            return (color,)
        elif self._port_mode.mode == self.MODE_REFLECTIVITY:
            #Emits when light reflectivity changes; unit: % (0-100)
            reflect = usbyte(data, 0)
            return (reflect,)
        elif self._port_mode.mode == self.MODE_RGB:
            #Emits when light reflectivity changes (RGB)
            red = ushort(data, 0)
            green = ushort(data, 2)
            blue = ushort(data, 4)
            return (red,green,blue)
        else:
            log.debug("Got Duplo train color sensor data while in unexpected mode: %r", self._port_mode)
            return ()


class DuploTrainBaseSpeaker(Peripheral):
    MODE_SOUND = 0x01
    MODE_TONE = 0x02

    def __init__(self, parent, port):
        super(DuploTrainBaseSpeaker, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_SPEAKER

    def play_sound(self, sound):
        self.set_port_mode(self.MODE_SOUND)
        payload = pack("<B", self.MODE_SOUND) + pack("<B", sound)

        msg = MsgPortOutput(self.port, MsgPortOutput.WRITE_DIRECT_MODE_DATA, payload)
        self._send_output(msg)

    def play_tone(self, tone):
        self.set_port_mode(self.MODE_TONE)
        payload = pack("<B", self.MODE_TONE) + pack("<B", tone)

        msg = MsgPortOutput(self.port, MsgPortOutput.WRITE_DIRECT_MODE_DATA, payload)
        self._send_output(msg)


class DuploTrainBaseSpeedometer(Peripheral):

    MODE_SPEED = 0x00

    def __init__(self, parent, port):
        super(DuploTrainBaseSpeedometer, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_SPEEDOMETER

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_SPEED:
            #Emits on speed change
            speed = sshort(data, 0)
            return (speed,)
        else:
            log.debug("Got Duplo train base speedometer data while in unexpected mode: %r", self._port_mode)
            return ()


class TechnicColorSensor(Peripheral):

    MODE_COLOR = 0x00
    MODE_REFLECTIVITY = 0x01
    MODE_AMBIENT_LIGHT = 0x02

    def __init__(self, parent, port):
        super(TechnicColorSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_COLOR_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_COLOR:
            #Emits when color sensor is activated
            color = usbyte(data, 0)
            if color <= 10:
                return (color,)
        elif self._port_mode.mode == self.MODE_REFLECTIVITY:
            #Emits when light reflectivity changes; unit: % (0-100)
            reflect = usbyte(data, 0)
            return (reflect,)
        elif self._port_mode.mode == self.MODE_AMBIENT_LIGHT:
            #Emits when ambient light changes; unit: % (0-100)
            ambient = usbyte(data, 0)
            return (ambient,)
        else:
            log.debug("Got Technic color sensor data while in unexpected mode: %r", self._port_mode)
            return ()


class TechnicDistanceSensor(Peripheral):

    MODE_DISTANCE = 0x00
    MODE_FAST_DISTANCE = 0x01

    SET_BRIGHTNESS = 0x05

    def __init__(self, parent, port):
        super(TechnicDistanceSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_DISTANCE_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_DISTANCE:
            #Emits when detected distance changes (slow samplint 40mm to 2500mm)
            distance = ushort(data, 0)
            return (distance,)
        elif self._port_mode.mode == self.MODE_FAST_DISTANCE:
            #Emits when detected distance changes (fast samplint 50mm to 320mm)
            distance = ushort(data, 0)
            return (distance,)
        else:
            log.debug("Got Technic distance sensor data while in unexpected mode: %r", self._port_mode)
            return ()

    def set_brightness(self, brightness_top_left, brightness_bottom_left, brightness_top_right, brightness_bottom_right):
        '''
        Sets brightness around the eyes.
        '''
        self.set_port_mode(self.SET_BRIGHTNESS)
        payload = pack("<B", self.SET_BRIGHTNESS) + pack("<B", brightness_top_left) + pack("<B", brightness_top_right) + pack("<B", brightness_bottom_left) + pack("<B", brightness_bottom_right)

        msg = MsgPortOutput(self.port, MsgPortOutput.WRITE_DIRECT_MODE_DATA, payload)
        self._send_output(msg)
        

class TechnicForceSensor(Peripheral):

    MODE_FORCE = 0x00
    MODE_TOUCHED = 0x01
    MODE_TAPPED = 0x02

    def __init__(self, parent, port):
        super(TechnicForceSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_FORCE_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_FORCE:
            #Unit: Newtons (0-10)
            force = usbyte(data, 0)
            return (force,)
        elif self._port_mode.mode == self.MODE_TOUCHED:
            #Unit: bool
            touched = True if usbyte(data, 0) else False
            return (touched,)
        elif self._port_mode.mode == self.MODE_TAPPED:
            #Unit: scale (0-3)
            tapped = usbyte(data, 0)
            return (tapped,)
        else:
            log.debug("Got Technic force sensor data while in unexpected mode: %r", self._port_mode)
            return ()


class MotionSensor(Peripheral):

    MODE_DISTANCE = 0x00

    def __init__(self, parent, port):
        super(MotionSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_MOTION_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_DISTANCE:
            #Measures distance; unit: millimeters
            distance = usbyte(data, 0)
            if usbyte(data, 1) == 1:
                distance += 255
            distance *= 10
            return (distance,)
        else:
            log.debug("Got motion sensor data while in unexpected mode: %r", self._port_mode)
            return ()
            

_MAX_VOLTAGE_VAL = {
    HubType.UNKNOWN_HUB: 9.615,
    HubType.WEDO2_SMART_HUB: 1,
    HubType.DUPLO_TRAIN_BASE: 6.4,
    HubType.POWERED_UP_REMOTE_CONTROL: 6.4,
}

_MAX_VOLTAGE_RAW = {
    HubType.UNKNOWN_HUB: 3893,
    HubType.WEDO2_SMART_HUB: 40,
    HubType.DUPLO_TRAIN_BASE: 3047,
    HubType.POWERED_UP_REMOTE_CONTROL: 3200,
    HubType.TECHNIC_HUB: 4095,

}

class VoltageSensor(Peripheral):
    #TODO: sensor says there are "L" and "S" values, but what are they?
    VOLTAGE_L = 0x00
    VOLTAGE_S = 0x01

    def __init__(self, parent, port):
        super(VoltageSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_VOLTAGE

    def _decode_port_data(self, msg):
        data = msg.payload
        val = ushort(data, 0)
        v = _MAX_VOLTAGE_VAL[self.hub.type] if self.hub.type in _MAX_VOLTAGE_VAL else _MAX_VOLTAGE_VAL[HubType.UNKNOWN_HUB]
        r = _MAX_VOLTAGE_RAW[self.hub.type] if self.hub.type in _MAX_VOLTAGE_RAW else _MAX_VOLTAGE_RAW[HubType.UNKNOWN_HUB]
        volts = v * val / r
        return (volts,)


_MAX_CURRENT_VAL = {
    HubType.UNKNOWN_HUB: 2444,
    HubType.WEDO2_SMART_HUB: 1,
    HubType.TECHNIC_HUB: 4175,
}

_MAX_CURRENT_RAW = {
    HubType.UNKNOWN_HUB: 4095,
    HubType.WEDO2_SMART_HUB: 1000,
    HubType.TECHNIC_HUB: 4095,

}

class CurrentSensor(Peripheral):
    #TODO: sensor says there are "L" and "S" values, but what are they?
    CURRENT_L = 0x00
    CURRENT_S = 0x01

    def __init__(self, parent, port):
        super(CurrentSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_CURRENT

    def _decode_port_data(self, msg):
        val = ushort(msg.payload, 0)
        v = _MAX_CURRENT_VAL[self.hub.type] if self.hub.type in _MAX_CURRENT_VAL else _MAX_CURRENT_VAL[HubType.UNKNOWN_HUB]
        r = _MAX_CURRENT_RAW[self.hub.type] if self.hub.type in _MAX_CURRENT_RAW else _MAX_CURRENT_RAW[HubType.UNKNOWN_HUB]
        milliampers = v * val / r
        return (milliampers,)       


class TechnicHubTemperatureSensor(Peripheral):

    MODE_TEMPERATURE = 0x00

    def __init__(self, parent, port):
        super(TechnicHubTemperatureSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_TEMPERATURE_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_TEMPERATURE:            
            #Emits when temperature changes by requested delta
            temperature = sshort(data, 0) * 0.1 #TODO: Is this correct?
            return (temperature,)
        else:
            log.debug("Got Technic hub temperature sensor data while in unexpected mode: %r", self._port_mode)
            return ()


class TechnicHubGestSensor(Peripheral):
    #TODO: What is this sensor?!

    MODE_GEST = 0x00

    def __init__(self, parent, port):
        super(TechnicHubGestSensor, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_GEST_SENSOR

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_GEST:
            #Emits when ???
            print("DEBUG: TechnicHubGestSensor: ", len(data)) #DEBUG
            temperature = usbyte(data, 0) #TODO: Is this correct?
            return (temperature,)
        else:
            log.debug("Got Technic hub gest sensor data while in unexpected mode: %r", self._port_mode)
            return ()

class RemoteControlButton(Peripheral):

    MODE_BUTTON_EVENT = 0x00

    BUTTON_UP = 0x01
    BUTTON_DOWN = 0xFF
    BUTTON_STOP = 0x7F
    BUTTON_RELEASED = 0x00

    def __init__(self, parent, port):
        super(RemoteControlButton, self).__init__(parent, port)
        self.type = MsgHubAttachedIO.DEV_REMOTE_CONTROL_BUTTON

    def _decode_port_data(self, msg):
        data = msg.payload
        if self._port_mode.mode == self.MODE_BUTTON_EVENT:
            #Emits when button on the remote is pressed/released
            event = usbyte(data, 0)
            return (event,)
        else:
            log.debug("Got remote control button data while in unexpected mode: %r", self._port_mode)
            return ()


class Button(Peripheral):
    """
    It's not really a peripheral, we use MsgHubProperties commands to interact with it.
    Ref. button state in MsgHubProperties.BUTTON_STATE_<X>
    """

    def __init__(self, parent):
        super(Button, self).__init__(parent, None)  # fake port 0 -> JK: None
        self.hub.add_message_handler(MsgHubProperties, self._props_msg)
        self.type = MsgHubAttachedIO.DEV_UNKNOWN

    def subscribe(self, callback, mode=None, update_delta=1):
        self.hub.send(MsgHubProperties(MsgHubProperties.BUTTON, MsgHubProperties.UPD_ENABLE))

        if callback:
            self._subscribers.add(callback)

    def unsubscribe(self, callback=None):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

        if not self._subscribers:
            self.hub.send(MsgHubProperties(MsgHubProperties.BUTTON, MsgHubProperties.UPD_DISABLE))

    def _props_msg(self, msg):
        """
        :type msg: MsgHubProperties
        """
        if msg.property == MsgHubProperties.BUTTON and msg.operation == MsgHubProperties.UPSTREAM_UPDATE:
            self._notify_subscribers(usbyte(msg.parameters, 0))


#-------------------------------------------------------------------------

PERIPHERAL_TYPES = {
    MsgHubAttachedIO.DEV_UNKNOWN: None,
    MsgHubAttachedIO.DEV_SIMOLE_MEDIUM_LINEAR_MOTOR: SimpleMediumLinearMotor,
    MsgHubAttachedIO.DEV_SYSTEM_TRAIN_MOTOR: SystemTrainMotor,
    MsgHubAttachedIO.DEV_LED_LIGHT: LEDLight,
    MsgHubAttachedIO.DEV_VOLTAGE: VoltageSensor,
    MsgHubAttachedIO.DEV_CURRENT: CurrentSensor,
    MsgHubAttachedIO.DEV_PIEZO_SOUND: None, #WeDo2's built-in buzzer; NOT supported!!! 
    MsgHubAttachedIO.DEV_RGB_LIGHT: LEDRGB, #HUB LED
    MsgHubAttachedIO.DEV_TILT: TiltSensor,
    MsgHubAttachedIO.DEV_MOTION_SENSOR: MotionSensor,
    MsgHubAttachedIO.DEV_VISION_SENSOR: VisionSensor, #Color distance senesor
    MsgHubAttachedIO.DEV_MEDIUM_LINEAR_MOTOR: MediumLinearMotor,
    MsgHubAttachedIO.DEV_MOVE_HUB_MEDIUM_LINEAR_MOTOR: MoveHubMediumLinearMotor, #Move Hub medium linear motor
    MsgHubAttachedIO.DEV_MOVE_HUB_TILT: MoveHubTiltSensor, #Move Hub tilt sensor
    MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_MOTOR: DuploTrainBaseMotor,
    MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_SPEAKER: DuploTrainBaseSpeaker,
    MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_COLOR_SENSOR: DuploTrainColorSensor,
    MsgHubAttachedIO.DEV_DUPLO_TRAIN_BASE_SPEEDOMETER: DuploTrainBaseSpeedometer,
    MsgHubAttachedIO.DEV_TECHNIC_LARGE_LINEAR_MOTOR: TechnicLargeLinearMotor, #Technic Control+
    MsgHubAttachedIO.DEV_TECHNIC_XLARGE_LINEAR_MOTOR: TechnicXLargeLinearMotor, #Technic Control+
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_ANGULAR_MOTOR: TechnicMediumAngularMotor, #Spike Prime
    MsgHubAttachedIO.DEV_TECHNIC_LARGE_ANGULAR_MOTOR: TechnicLargeAngularMotor, #Spike Prime
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_GEST_SENSOR: TechnicHubGestSensor, #What is this?
    MsgHubAttachedIO.DEV_REMOTE_CONTROL_BUTTON: RemoteControlButton,
    MsgHubAttachedIO.DEV_REMOTE_CONTROL_RSSI: None, #What is this?
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_ACCELEROMETER: TechnicHubAccelerometerSensor,
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_GYRO_SENSOR: TechnicHubGyroSensor,
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_TILT_SENSOR: TechnicHubTiltSensor,
    MsgHubAttachedIO.DEV_TECHNIC_MEDIUM_HUB_TEMPERATURE_SENSOR: TechnicHubTemperatureSensor,
    MsgHubAttachedIO.DEV_TECHNIC_COLOR_SENSOR: TechnicColorSensor, #Spike Prime
    MsgHubAttachedIO.DEV_TECHNIC_DISTANCE_SENSOR: TechnicDistanceSensor, #Spike Prime
    MsgHubAttachedIO.DEV_TECHNIC_FORCE_SENSOR: TechnicForceSensor #Spike Prime
}

#-------------------------------------------------------------------------