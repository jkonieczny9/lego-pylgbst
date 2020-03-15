import logging

import pygatt

from pylgbst.comms import Connection, LPF2_HUB_HW_UUID_CHAR
from pylgbst.utilities import str2hex

log = logging.getLogger('comms-pygatt')


class GattoolConnection(Connection):
    """
    Loops with timeout of 1 seconds to find device with proper name or MAC address.

    :type _conn_hnd: pygatt.backends.bgapi.device.BGAPIBLEDevice
    """

    def __init__(self, controller='hci0'):
        Connection.__init__(self)
        self.backend = lambda: pygatt.GATTToolBackend(hci_device=controller)
        self._conn_hnd = None
        self._adapter = None

    def connect(self, hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
        '''
        NOTE: Use reset=False to connect for 2nd and further devices to avoid disconnecting already connected devices.
        '''
        log.debug("Trying to connect client to hub with MAC: %s", hub_mac)
        if self._adapter is None: 
            self._adapter = self.backend()
            if isinstance(self._adapter, pygatt.GATTToolBackend):
                self._adapter.start(reset_on_start=reset)
            else:
                self._adapter.start(reset=reset)
        assert(self._adapter is not None)

        while not self._conn_hnd:
            log.info("Discovering devices...")
            devices = self._adapter.scan(1)
            log.debug("Devices: %s", devices)

            for dev in devices:
                address = dev['address']
                name = dev['name']
                if self._is_device_matched(address, name, hub_mac, hub_name, prohibited_hub_mac):
                    self._conn_hnd = self._adapter.connect(address)
                    self.name = name
                    self.address = address
                    break

            if self._conn_hnd:
                break

        return self

    def disconnect(self):
        self._conn_hnd.disconnect()

    def write(self, handle, data):
        log.debug("Writing to handle %s: %s", handle, str2hex(data))
        return self._conn_hnd.char_write_handle(handle, bytearray(data))

    def set_notify_handler(self, handler):
        self._conn_hnd.subscribe(LPF2_HUB_HW_UUID_CHAR, handler)

    def is_alive(self):
        return True


class BlueGigaConnection(GattoolConnection):
    def __init__(self):
        super(BlueGigaConnection, self).__init__()
        self.backend = lambda: pygatt.BGAPIBackend()
