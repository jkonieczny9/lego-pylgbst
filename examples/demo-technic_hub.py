# coding=utf-8
import time
from time import sleep
import sys, os

sys.path.insert(0, os.environ.get('PYLGBST_ROOT'))

from pylgbst import *
from pylgbst.peripherals import BasicMotor, TiltSensor, CurrentSensor, VoltageSensor, VisionSensor, COLORS, COLOR_BLACK
from pylgbst.hub import HubType, HUB_NAMES, TechnicHub
from pylgbst.messages import MsgHubAttachedIO

log = logging.getLogger("demo-TechnicHub")


def demo_led_colors(hub):
    # LED colors demo
    log.info("LED colors demo")

    # We get a response with payload and port, not x and y here...
    def colour_callback(**named):
        log.info("LED Color callback: %s", named)

    hub_led = hub.get_device_by_port_name("HUB_LED")
    hub_led.subscribe(colour_callback)
    for color in list(COLORS.keys())[1:] + [COLOR_BLACK]:
        log.info("Setting LED color to: %s", COLORS[color])
        hub_led.set_color(color)
        sleep(1)
    hub_led.unsubscribe(colour_callback)


def demo_motors_timed(hub, port_name="A"):
    log.info("Motors movement demo: timed")
    motor = hub.get_device_by_port_name(port_name)
    if not issubclass(motor, BasicMotor):
        log.warning("Motor not found on port " + port_name)
    for level in range(0, 101, 10):
        level /= 100.0
        log.info("Speed level: %s%%", level * 100)
        motor.set_time(0.2, level)


def demo_motors_angled(hub, port_name="A"):
    log.info("Motors movement demo: angled")
    motor = hub.get_device_by_port_name(port_name)
    if not issubclass(motor, BasicMotor):
        log.warning("Motor not found on port " + port_name)
    for angle in range(0, 361, 90):
        log.info("Angle: %s", angle)
        motor.rotate_by_angle(angle, 1)
        sleep(1)
        motor.rotate_by_angle(angle, -1)
        sleep(1)


def demo_tilt_sensor(hub):
    log.info("Tilt sensor test. Turn device in different ways.")
    demo_tilt_sensor.cnt = 0
    limit = 10

    def callback(state):
        demo_tilt_sensor.cnt += 1
        x, y, z = state
        log.info("Tilt #%s of %s: x=%d, y=%d, z=%d", demo_tilt_sensor.cnt, limit, x, y, z)

    hub_tilt = hub.get_device_by_port_name("TILT_SENSOR")
    hub_tilt.subscribe(callback)
    while demo_tilt_sensor.cnt < limit:
        time.sleep(1)

    hub_tilt.unsubscribe(callback)


def demo_color_sensor(hub):
    log.info("Color sensor test: wave your hand in front of it")
    demo_color_sensor.cnt = 0
    limit = 20

    def callback_color(color):
        demo_color_sensor.cnt += 1
        log.info("#%s/%s: Color %s", demo_color_sensor.cnt, limit, COLORS[color] if color is not None else "none")

    def callback_distance(distance):
        demo_color_sensor.cnt += 1
        log.info("#%s/%s: Distance %s", demo_color_sensor.cnt, limit, distance)

    def callback_color_distance(color, distance=None):
        demo_color_sensor.cnt += 1
        log.info("#%s/%s: Color %s, distance %s", demo_color_sensor.cnt, limit, COLORS[color] if color is not None else "none", distance)

    mode = VisionSensor.COLOR_AND_DISTANCE
    if mode == VisionSensor.COLOR:
        fcbck = callback_color
    elif mode == VisionSensor.DISTANCE:
        fcbck = callback_distance
    elif mode == VisionSensor.COLOR_AND_DISTANCE:
        fcbck = callback_color_distance
    else:
        assert(0)

    hub_vision = hub.get_devices_by_type(MsgHubAttachedIO.DEV_VISION_SENSOR)
    assert(len(hub_vision) > 0)
    hub_vision = hub_vision[0]
    hub_vision.subscribe(callback=fcbck, mode=mode)
    while demo_color_sensor.cnt < limit:
        time.sleep(1)

    hub_vision.unsubscribe(fcbck)


def demo_motor_sensors(hub):
    log.info("Motor rotation sensors test. Rotate all available motors once")
    port_names = ["A","B","C","D"]
    demo_motor_sensors.states = {"A": 0, "B": 0, "C": 0, "D": 0}
    max_degrees = 30

    def callback_a(param1):
        demo_motor_sensors.states["A"] = param1
        log.info("A=%s", demo_motor_sensors.states)

    def callback_b(param1):
        demo_motor_sensors.states["B"] = param1
        log.info("B=%s", demo_motor_sensors.states)

    def callback_c(param1):
        demo_motor_sensors.states["C"] = param1
        log.info("C=%s", demo_motor_sensors.states)
    
    def callback_d(param1):
        demo_motor_sensors.states["D"] = param1
        log.info("D=%s", demo_motor_sensors.states)

    hub_motor_callbacks = {"A": callback_a, "B": callback_b, "C": callback_c, "D": callback_d}

    hub_motors = []
    for port_name in port_names:
        motor = hub.get_device_by_port_name(port_name)
        if not issubclass(motor, BasicMotor):
            log.warning("Motor not found on port " + port_name)
            motor = None
        else:
            motor.subscribe(hub_motor_callbacks[port_name])
            #motor.preset_encoder(degrees=0)
            motor.rotate_by_angle(360, speed_primary=5)
        hub_motors.append(motor)

    while True:
        is_done = True
        for port_name in port_names:
            if hub_motors[port_name] is None: 
                continue
            if abs(demo_motor_sensors.states[port_name]) < max_degrees:
                is_done = False
        if is_done:
            break
        time.sleep(1)

    for port_name in port_names:
        if hub_motors[port_name] is not None: 
            hub_motors[port_name].unsubscribe(hub_motor_callbacks[port_name])


def demo_voltage(hub):
    def callback1(value):
        log.info("Amperage: %s", value)

    def callback2(value):
        log.info("Voltage: %s", value)

    hub_current = hub.get_device_by_port_name("CURRENT")
    hub_current.subscribe(callback1, mode=CurrentSensor.CURRENT_L, update_delta=0)
    hub_current.subscribe(callback1, mode=CurrentSensor.CURRENT_L, update_delta=1)

    hub_voltage = hub.get_device_by_port_name("VOLTAGE")
    hub_voltage.subscribe(callback2, mode=VoltageSensor.VOLTAGE_L, update_delta=0)
    hub_voltage.subscribe(callback2, mode=VoltageSensor.VOLTAGE_L, update_delta=1)
    time.sleep(5)

    hub_current.unsubscribe(callback1)
    hub_voltage.unsubscribe(callback2)


def demo_all(hub):
    demo_voltage(hub)
    demo_led_colors(hub)
    demo_motors_timed(hub)
    demo_motors_angled(hub)
    demo_tilt_sensor(hub)
    demo_color_sensor(hub)
    demo_motor_sensors(hub)


DEMO_CHOICES = {
    'all': demo_all,
    'voltage': demo_voltage,
    'led_colors': demo_led_colors,
    'motors_timed': demo_motors_timed,
    'motors_angled': demo_motors_angled,
    'tilt_sensor': demo_tilt_sensor,
    'color_sensor': demo_color_sensor,
    'motor_sensors': demo_motor_sensors,
}


def get_options():
    import argparse
    arg_parser = argparse.ArgumentParser(
        description='Demonstrate move-hub communications',
    )
    arg_parser.add_argument(
        '-c', '--connection',
        default='auto://',
        help='''Specify connection URL to use, `protocol://mac?param=X` with protocol in:
    "gatt","pygatt","gattlib","gattool", "bluepy","bluegiga"'''
    )
    arg_parser.add_argument(
        '-d', '--demo',
        default='all',
        choices=sorted(DEMO_CHOICES.keys()),
        help="Run a particular demo, default all"
    )
    return arg_parser


def connection_from_url(url):
    import pylgbst
    if url == 'auto://':
        return None
    try:
        from urllib.parse import urlparse, parse_qs
    except ImportError:
        from urlparse import urlparse, parse_qs
    parsed = urlparse(url)
    name = 'get_connection_%s' % parsed.scheme
    factory = getattr(pylgbst, name, None)
    if not factory:
        msg = "Unrecognised URL scheme/protocol, expect a get_connection_<protocol> in pylgbst: %s"
        raise ValueError(msg % parsed.protocol)
    params = {}
    if parsed.netloc.strip():
        params['hub_mac'] = parsed.netloc
    for key, value in parse_qs(parsed.query).items():
        if len(value) == 1:
            params[key] = value[0]
        else:
            params[key] = value
    if 'hub_mac' not in params and 'hub_name' not in params:
        params['hub_name'] = HUB_NAMES[HubType.TECHNIC_HUB]
    return factory(
        **params
    )


if __name__ == '__main__':
    logging_level = logging.INFO #logging.DEBUG #logging.INFO
    logging.basicConfig(level=logging_level)
    parser = get_options()
    options = parser.parse_args()
    parameters = {}
    try:
        connection = connection_from_url(options.connection)
        parameters['connection'] = connection
    except ValueError as err:
        parser.error(err.args[0])

    hub = TechnicHub(**parameters)
    assert(hub.check_hub_type())
    try:
        demo = DEMO_CHOICES[options.demo]
        demo(hub)
    finally:
        hub.disconnect()
