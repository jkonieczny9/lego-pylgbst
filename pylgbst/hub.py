import threading
import time

from pylgbst import get_connection_auto
from pylgbst.comms import HUB_HARDWARE_HANDLE
from pylgbst.messages import *
from pylgbst.utilities import hex2int, str2hex, usbyte, sbyte, ushort, sshort, decode_mac, decode_version, queue

#-------------------------------------------------------------------------

log = logging.getLogger('hub')

#-------------------------------------------------------------------------

class HubType(object):
    UNKNOWN_HUB = -1
    WEDO2_SMART_HUB = BLEManufacturerData.WEDO2_ID
    MOVE_HUB = BLEManufacturerData.MOVE_HUB_ID
    POWERED_UP_HUB = BLEManufacturerData.POWERED_UP_HUB_ID
    POWERED_UP_REMOTE_CONTROL = BLEManufacturerData.POWERED_UP_REMOTE_CONTROL_ID
    DUPLO_TRAIN_BASE = BLEManufacturerData.DUPLO_TRAIN_BASE_ID
    TECHNIC_HUB = BLEManufacturerData.TECHNIC_HUB_ID #Control+/Technic Hub

HUB_NAMES = {
    HubType.UNKNOWN_HUB: "Unknown",
    HubType.WEDO2_SMART_HUB: "WeDo2 Smart Hub",
    HubType.MOVE_HUB: "Move Hub",
    HubType.POWERED_UP_HUB: "Powered Up Hub",
    HubType.POWERED_UP_REMOTE_CONTROL: "Powered Up Remote Control",
    HubType.DUPLO_TRAIN_BASE: "Duplo Train Base",
    HubType.TECHNIC_HUB: "Technic Hub",
}

#-------------------------------------------------------------------------

class Hub(object):
    """
    :type connection: pylgbst.comms.Connection
    :type peripherals: dict[int,Peripheral]
    """

    def __init__(self, connection=None):
        self.type = HubType.UNKNOWN_HUB
        self.peripherals = {}
        self.port_map = {}
        self.internal_ports = []
        self.button = None
        self.hub_name = ""
        self.primary_mac = "00:00:00:00:00:00"
        self.secondary_mac = "00:00:00:00:00:00"
        self.system_type_id = None
        self.manufacturer_id = None
        self.firmware_version = "0.0.00.0000"
        self.hardware_version = "0.0.00.0000"
        self.battery_level = None #100
        self.rssi = None #-60

        self._msg_handlers = []
        self._sync_request = None
        self._sync_replies = queue.Queue(1)
        self._sync_lock = threading.Lock()

        self.add_message_handler(MsgHubAttachedIO, self._handle_device_change)
        self.add_message_handler(MsgPortValueSingle, self._handle_sensor_data)
        self.add_message_handler(MsgPortValueCombined, self._handle_sensor_data)
        self.add_message_handler(MsgGenericError, self._handle_error)
        self.add_message_handler(MsgHubAction, self._handle_action)
        self.add_message_handler(MsgHubProperties, self._handle_properties)

        if not connection:
            connection = get_connection_auto()
        self.connection = connection
        self.connection.set_notify_handler(self._notify)
        self.connection.enable_notifications()

        self.hub_name = self.request_hub_name()
        self.primary_mac = self.request_primary_mac()
        self.secondary_mac = self.request_secondary_mac()
        self.system_type_id = self.request_system_type_id()
        self.manufacturer_id = self.request_manufacturer_id()
        self.firmware_version = self.request_firmware_versione()
        self.hardware_version = self.request_hardware_version()
        self.rssi = self.request_rssi()
        self.battery_level = self.request_battery_level()
        self._start_property_updates()

    def __del__(self):
        if self.connection and self.connection.is_alive():
            self.connection.disconnect()

    def name(self):
        if not self.connection: return None
        return self.connection.name

    def address(self):
        if not self.connection: return None
        return self.connection.address

    def is_port_virtual(self, port):
        return self.peripherals[port].is_port_virtual()

    def ports(self):
        return self.port_map.keys()

    def port_name(self, port):
        for port_name in self.port_map:
            if self.port_map[port_name] == port:
                return port_name

    def get_devices_by_type(self, device_type):
        devices = []
        for port in self.peripherals:
            dev = self.peripherals[port]
            if dev.type == device_type:
                devices.append(dev)
        return devices

    def get_device_by_port_name(self, port_name):
        if port_name not in self.port_map: return None
        port = self.port_map[port_name]
        if port not in self.peripherals: return None
        return self.peripherals[port]

    def wait_for_devices(self, port_names=None):
        if not port_names:
            port_names = self.internal_ports
        for num in range(0, 100):
            devices = (self.get_device_by_port_name(p) for p in port_names)
            if all(devices):
                log.debug("All devices are present: %s", devices)
                return
            log.debug("Waiting for devices to appear: %s", devices)
            time.sleep(0.1)
        log.warning("Got only these devices: %s", devices)

    def request_hub_name(self):
        return "%s" % self.send(MsgHubProperties(MsgHubProperties.ADVERTISE_NAME, MsgHubProperties.UPD_REQUEST)).parameters

    def request_primary_mac(self):
        return decode_mac(self.send(MsgHubProperties(MsgHubProperties.PRIMARY_MAC, MsgHubProperties.UPD_REQUEST)).parameters)

    def request_secondary_mac(self):
        return decode_mac(self.send(MsgHubProperties(MsgHubProperties.SECONDARY_MAC, MsgHubProperties.UPD_REQUEST)).parameters)

    def request_system_type_id(self):
        return hex2int(str2hex(self.send(MsgHubProperties(MsgHubProperties.SYSTEM_TYPE_ID, MsgHubProperties.UPD_REQUEST)).parameters))

    def request_manufacturer_id(self):
        return "%s" % self.send(MsgHubProperties(MsgHubProperties.MANUFACTURER, MsgHubProperties.UPD_REQUEST)).parameters

    def request_firmware_versione(self):
        return decode_version(self.send(MsgHubProperties(MsgHubProperties.FW_VERSION, MsgHubProperties.UPD_REQUEST)).parameters)
        
    def request_hardware_version(self):
        return decode_version(self.send(MsgHubProperties(MsgHubProperties.HW_VERSION, MsgHubProperties.UPD_REQUEST)).parameters)

    def request_rssi(self):
        return sbyte(self.send(MsgHubProperties(MsgHubProperties.RSSI, MsgHubProperties.UPD_REQUEST)).parameters, 0)

    def request_battery_level(self):
        return usbyte(self.send(MsgHubProperties(MsgHubProperties.VOLTAGE_PERC, MsgHubProperties.UPD_REQUEST)).parameters, 0)

    def report_status(self):
        log.info("Hub status for %s:" % self.name() + "\n"
        + " Name: %s" % self.hub_name + "\n"
        + " Primary MAC: %s" % self.primary_mac + "\n"
        + " Secondary MAC: %s" % self.secondary_mac + "\n"
        + " System type ID: 0x%x" % self.system_type_id + "\n"
        + " Manufacturer ID: %s" % self.manufacturer_id + "\n"
        + " Firmware version: %s" % self.firmware_version + "\n"
        + " Hardware version: %s" % self.hardware_version + "\n"
        + " RSSI: %s" % self.rssi + "\n"
        + " Battery level: %s%%" % self.battery_level + "\n")

    def add_message_handler(self, classname, callback):
        self._msg_handlers.append((classname, callback))

    def send(self, msg):
        """
        :type msg: pylgbst.messages.DownstreamMsg
        :rtype: pylgbst.messages.UpstreamMsg
        """
        log.debug("Send message: %r", msg)
        msgbytes = msg.bytes()
        if msg.needs_reply:
            with self._sync_lock:
                assert not self._sync_request, "Pending request %r while trying to put %r" % (self._sync_request, msg)
                self._sync_request = msg
                log.debug("Waiting for sync reply to %r...", msg)

            self.connection.write(HUB_HARDWARE_HANDLE, msgbytes)
            resp = self._sync_replies.get()
            log.debug("Fetched sync reply: %r", resp)
            if isinstance(resp, MsgGenericError):
                raise RuntimeError(resp.message())
            return resp
        else:
            self.connection.write(HUB_HARDWARE_HANDLE, msgbytes)
            return None

    def _notify(self, handle, data):
        log.debug("Notification on %s: %s", handle, str2hex(data))

        msg = self._get_upstream_msg(data)

        with self._sync_lock:
            if self._sync_request:
                if self._sync_request.is_reply(msg):
                    log.debug("Found matching upstream msg: %r", msg)
                    self._sync_replies.put(msg)
                    self._sync_request = None

        for msg_class, handler in self._msg_handlers:
            if isinstance(msg, msg_class):
                log.debug("Handling msg with %s: %r", handler, msg)
                handler(msg)

    def _get_upstream_msg(self, data):
        msg_type = usbyte(data, 2)
        msg = None
        for msg_kind in UPSTREAM_MSGS:
            if msg_type == msg_kind.TYPE:
                msg = msg_kind.decode(data)
                log.debug("Decoded message: %r", msg)
                break
        assert msg
        return msg

    def _handle_properties(self, msg):
        if msg.property == MsgHubProperties.VOLTAGE_PERC:
            self.battery_level = usbyte(msg.parameters, 0)
            log.info("Voltage: %s%%", self.battery_level)
            if self.battery_level < 10.0:
                log.warning("Low battery level, check power source!")
        elif msg.property == MsgHubProperties.RSSI:
            self.rssi = sbyte(msg.parameters, 0)
            log.info("RSSI: %s", self.rssi)
        elif msg.property == MsgHubProperties.ADVERTISE_NAME:
            self.hub_name = "%s" % msg.parameters
            log.info("Hub name: %s", self.hub_name)
        elif msg.property == MsgHubProperties.PRIMARY_MAC:
            self.primary_mac = decode_mac(msg.parameters)
            log.info("Primary MAC: %s", self.primary_mac)
        elif msg.property == MsgHubProperties.SECONDARY_MAC:
            self.secondary_mac = decode_mac(msg.parameters)
            log.info("Secondary MAC: %s", self.secondary_mac)
        elif msg.property == MsgHubProperties.SYSTEM_TYPE_ID:
            self.system_type_id = hex2int(str2hex(msg.parameters))
            log.info("System type ID: 0x%x", self.system_type_id)
        elif msg.property == MsgHubProperties.MANUFACTURER:
            self.manufacturer_id = "%s" % msg.parameters
            log.info("Manufacturer ID: %s", self.manufacturer_id)        
        elif msg.property == MsgHubProperties.FW_VERSION:
            self.firmware_version = decode_version(msg.parameters)
            log.info("Firmware version: %s", self.firmware_version)
        elif msg.property == MsgHubProperties.HW_VERSION:
            self.hardware_version = decode_version(msg.parameters)
            log.info("Hardware version: %s", self.hardware_version)  

    def _handle_error(self, msg):
        log.warning("Command error: %s", msg.message())
        with self._sync_lock:
            if self._sync_request:
                self._sync_request = None
                self._sync_replies.put(msg)

    def _handle_action(self, msg):
        """
        :type msg: MsgHubAction
        """
        if msg.action == MsgHubAction.UPSTREAM_DISCONNECT:
            log.warning("Hub disconnects")
            self.connection.disconnect()
        elif msg.action == MsgHubAction.UPSTREAM_SHUTDOWN:
            log.warning("Hub switches off")
            self.connection.disconnect()

    def _handle_device_change(self, msg):
        if msg.event == MsgHubAttachedIO.EVENT_DETACHED:
            log.debug("Detaching peripheral: %s", self.peripherals[msg.port])
            if self.is_port_virtual(msg.port):
                self.port_map.pop(self.port_name(msg.port))
            self.peripherals.pop(msg.port)
            return

        assert msg.event in (msg.EVENT_ATTACHED, msg.EVENT_ATTACHED_VIRTUAL)
        port = msg.port
        dev_type = ushort(msg.payload, 0)

        from pylgbst.peripherals import PERIPHERAL_TYPES
        if dev_type in PERIPHERAL_TYPES and PERIPHERAL_TYPES[dev_type] is not None:
            log.debug("Adding periphreal type 0x%x on port 0x%x", dev_type, port)
            self.peripherals[port] = PERIPHERAL_TYPES[dev_type](self, port)
        else:
            log.warning("Unsupported peripheral type 0x%x on port 0x%x", dev_type, port)
            from pylgbst.peripherals import Peripheral
            self.peripherals[port] = Peripheral(self, port)

        log.info("Attached peripheral: %s", self.peripherals[msg.port])

        if msg.event == msg.EVENT_ATTACHED:
            hw_revision = msg.payload[2:6]
            sw_revision = msg.payload[6:10]
            log.info("Port: 0x%x, Hardware version: %s, Software version: %s", msg.port, decode_version(hw_revision), decode_version(sw_revision))
            del hw_revision, sw_revision
        elif msg.event == msg.EVENT_ATTACHED_VIRTUAL:
            firts_port_name = usbyte(msg.payload, 2)
            second_port_name = usbyte(msg.payload, 3)
            virtual_port_name = firts_port_name + second_port_name
            self.peripherals[port].virtual_ports = (firts_port_name, second_port_name)
            self.port_map[virtual_port_name] = port

    def _handle_sensor_data(self, msg):
        assert isinstance(msg, (MsgPortValueSingle, MsgPortValueCombined))
        if msg.port not in self.peripherals:
            log.warning("Notification on port with no device: 0x%x", msg.port)
            return

        device = self.peripherals[msg.port]
        device.queue_port_data(msg)

    def _start_property_updates(self):
        self.send(MsgHubProperties(MsgHubProperties.VOLTAGE_PERC, MsgHubProperties.UPD_ENABLE))        
        self.send(MsgHubProperties(MsgHubProperties.RSSI, MsgHubProperties.UPD_ENABLE))

    def _stop_property_updates(self):
        self.send(MsgHubProperties(MsgHubProperties.VOLTAGE_PERC, MsgHubProperties.UPD_DISABLE))        
        self.send(MsgHubProperties(MsgHubProperties.RSSI, MsgHubProperties.UPD_DISABLE))

    def disconnect(self):
        self._stop_property_updates()
        self.send(MsgHubAction(MsgHubAction.DISCONNECT))

    def switch_off(self):
        self._stop_property_updates()
        self.send(MsgHubAction(MsgHubAction.SWITCH_OFF))

    def check_hub_type(self):
        return self.system_type_id == self.type


class MoveHub(Hub):
    """
    Class implementing Lego Boost's MoveHub specifics

    :type led: LEDRGB
    :type tilt_sensor: TiltSensor
    :type button: Button
    :type current: Current
    :type voltage: Voltage
    :type vision_sensor: pylgbst.peripherals.VisionSensor
    :type port_C: Peripheral
    :type port_D: Peripheral
    :type motor_A: EncodedMotor
    :type motor_B: EncodedMotor
    :type motor_AB: EncodedMotor
    :type motor_external: EncodedMotor
    """

    # noinspection PyTypeChecker
    def __init__(self, connection=None):
        super(MoveHub, self).__init__(connection)
        self.type = HubType.MOVE_HUB
        self.info = {}

        # shorthand fields
        from pylgbst.peripherals import Button
        self.button = Button(self)
        self.port_map = {
            "A": 0x00,
            "B": 0x01,
            "C": 0x02,
            "D": 0x03,
            "AB": 0x10,
            "HUB_LED": 0x32,
            "TILT_SENSOR": 0x3A,
            "CURRENT": 0x3B,
            "VOLTAGE": 0x3C,
        }
        self.internal_ports = ["A", "B", "AB", "HUB_LED", "CURRENT", "VOLTAGE", "TILT_SENSOR"]

        self.wait_for_devices()
        self.report_status()

class TechnicHub(Hub):
    """
    Class implementing Lego Technic Smart Hub (Control+) specifics

    :type button: Button
    :type led: LEDRGB
    :type current: CurrentSensor
    :type voltage: VoltageSensor
    :type accelerometer_sensor: AccelerometerSensor
    :type gyro_sensor: GyroSensor
    :type tilt_sensor: TiltSensor
    :type port_A: Peripheral
    :type port_B: Peripheral
    :type port_C: Peripheral
    :type port_D: Peripheral
    """    

    # noinspection PyTypeChecker
    def __init__(self, connection=None):
        super(TechnicHub, self).__init__(connection)
        self.type = HubType.TECHNIC_HUB
        self.info = {}

        # peripherals
        from pylgbst.peripherals import Button
        self.button = Button(self)
        self.port_map = {
            "A": 0x00,
            "B": 0x01,
            "C": 0x02,
            "D": 0x03,
            "HUB_LED": 0x32,
            "CURRENT": 0x3B,
            "VOLTAGE": 0x3C,
            "TEMPERATURE": 0x3D, #TODO: What is this?
            "TEMPERATURE2": 0x60, #TODO: What is this?
            "ACCELEROMETER": 0x61,
            "GYRO_SENSOR": 0x62,
            "TILT_SENSOR": 0x63
        }
        self.internal_ports = ["HUB_LED", "CURRENT", "VOLTAGE", "TEMPERATURE", "TEMPERATURE2", "ACCELEROMETER", "GYRO_SENSOR", "TILT_SENSOR"]

        self.wait_for_devices()
        self._start_property_updates()
        self.report_status()

    def _start_property_updates(self):
        super(TechnicHub, self)._start_property_updates()
        #port_temperature = self.get_device_by_port_name("TEMPERATURE")
        #if port_temperature: 
        #    port_temperature.set_port_mode(port_temperature.MODE_TEMPERATURE, send_updates=1, update_delta=10)
        #port_temperature2 = self.get_device_by_port_name("TEMPERATURE2")
        #if port_temperature2: 
        #    port_temperature2.set_port_mode(port_temperature2.MODE_TEMPERATURE, send_updates=1, update_delta=10)

    def _stop_property_updates(self):
        #port_temperature = self.get_device_by_port_name("TEMPERATURE")
        #if port_temperature: 
        #    port_temperature.set_port_mode(port_temperature.MODE_TEMPERATURE, send_updates=0)
        #port_temperature2 = self.get_device_by_port_name("TEMPERATURE2")
        #if port_temperature2: 
        #    port_temperature2.set_port_mode(port_temperature2.MODE_TEMPERATURE, send_updates=0)
        super(TechnicHub, self)._stop_property_updates()        

#-------------------------------------------------------------------------

HUB_TYPES = {
    HubType.UNKNOWN_HUB: Hub,
    HubType.WEDO2_SMART_HUB: None, #NOT supported!!!
    HubType.MOVE_HUB: MoveHub,
    HubType.POWERED_UP_HUB: None,
    HubType.POWERED_UP_REMOTE_CONTROL: None,
    HubType.DUPLO_TRAIN_BASE: None,
    HubType.TECHNIC_HUB: TechnicHub,
}

