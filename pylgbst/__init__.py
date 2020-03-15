import logging
import traceback

from pylgbst.comms import DebugServer

log = logging.getLogger('pylgbst')


def get_connection_pygatt(controller='hci0', hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
    from pylgbst.comms.cpygatt import GattoolConnection
    return GattoolConnection(controller).connect(hub_mac, hub_name, prohibited_hub_mac, reset)


def get_connection_bluegiga(controller=None, hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
    del controller  # to prevent code analysis warning
    from pylgbst.comms.cpygatt import BlueGigaConnection
    return BlueGigaConnection().connect(hub_mac, hub_name, prohibited_hub_mac, reset)


def get_connection_gattool(controller='hci0', hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
    from pylgbst.comms.cpygatt import GattoolConnection
    return GattoolConnection(controller).connect(hub_mac, hub_name, prohibited_hub_mac, reset)


def get_connection_gatt(controller='hci0', hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
    from pylgbst.comms.cgatt import GattConnection
    return GattConnection(controller).connect(hub_mac, hub_name, prohibited_hub_mac, reset)


def get_connection_gattlib(controller='hci0', hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
    from pylgbst.comms.cgattlib import GattLibConnection
    return GattLibConnection(controller).connect(hub_mac, hub_name, prohibited_hub_mac, reset)


def get_connection_bluepy(controller='hci0', hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
    from pylgbst.comms.cbluepy import BluepyConnection
    return BluepyConnection(controller).connect(hub_mac, hub_name, prohibited_hub_mac, reset)


def get_connection_auto(controller='hci0', hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
    fns = [
        get_connection_pygatt,
        get_connection_bluegiga,
        get_connection_gattool,
        get_connection_gatt,
        get_connection_gattlib,
        get_connection_bluepy,
    ]

    conn = None
    for fn in fns:
        try:
            logging.info("Trying %s", fn.__name__)
            conn = fn(controller, hub_mac, hub_name, prohibited_hub_mac, reset)
            if conn is not None: break
        except KeyboardInterrupt:
            raise
        except BaseException:
            logging.debug("Failed: %s", traceback.format_exc())

    if conn is None:
        raise Exception("Failed to autodetect connection, make sure you have installed prerequisites")

    logging.info("Succeeded with %s", conn.__class__.__name__)
    return conn

def get_connection_by_name(module_name="auto", controller='hci0', hub_mac=None, hub_name=None, prohibited_hub_mac=None, reset=True):
    if module_name == "pygatt":
        return get_connection_pygatt(controller, hub_mac, hub_name, prohibited_hub_mac, reset)
    elif module_name == "bluepy":
        return get_connection_bluepy(controller, hub_mac, hub_name, prohibited_hub_mac, reset)
    elif module_name == "bluegiga":
        return get_connection_bluegiga(controller, hub_mac, hub_name, prohibited_hub_mac, reset)
    elif module_name == "gatt":
        return get_connection_gatt(controller, hub_mac, hub_name, prohibited_hub_mac, reset)
    elif module_name == "gattool":
        return get_connection_gattool(controller, hub_mac, hub_name, prohibited_hub_mac, reset)
    elif module_name == "gattlib":
        return get_connection_gattlib(controller, hub_mac, hub_name, prohibited_hub_mac, reset)
    else:
        return get_connection_auto(controller, hub_mac, hub_name, prohibited_hub_mac, reset)


def start_debug_server(iface="hci0", port=9090):
    server = DebugServer(get_connection_auto(iface))
    try:
        server.start(port)
    finally:
        server.connection.disconnect()
