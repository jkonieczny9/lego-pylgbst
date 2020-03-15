import Tkinter as tk
import time
import os, sys
import argparse
from types import FunctionType

sys.path.insert(0, os.environ.get('PYLGBST_ROOT'))

from pylgbst import *
from pylgbst.peripherals import BasicMotor, TiltSensor, CurrentSensor, VoltageSensor, COLORS, COLOR_BLACK
from pylgbst.hub import HubType, HUB_NAMES, TechnicHub
from pylgbst.messages import MsgHubAttachedIO

#--------------------------------------------------------------------------

log = logging.getLogger("demo-liebherr")

#--------------------------------------------------------------------------

HUB_IDS = ["up", "down"]
LABEL_COLORS = {"up": "dark green",
                "down": "dark blue"
}
HUB_PORTS = {
        "up": ["A", "B", "C", "D"],
        "down": ["A", "B", "D"]
}
HUB_PORT_FUNCS = {
        "up": ["Arm up/down", "Bend arm", "Bend spoon", "Open spoon"],
        "down": ["Left", "Right", "Rotate"]
}
MOTOR_ACTIONS = ["start", "stop", "up", "down"]

DELAY      = 30
HUB_DELAY = 0.3
BUTTON_WIDTH = 250
BUTTON_HEIGHT = 25
HOR_MARGIN = 10
VER_MARGIN = 5
DEFAULT_SPEED = 50
MAX_SPEED = 100
MIN_SPEED = 1
SPEED_CHANGE = 20

#--------------------------------------------------------------------------

logging_level = logging.INFO #logging.DEBUG #logging.INFO
logging.basicConfig(level=logging_level)

#--------------------------------------------------------------------------

arg_parser = argparse.ArgumentParser(description='Lego Liebherr-9800 Control')
arg_parser.add_argument('-c', '--connection', default='auto', help='Specify connection module: "gatt", "pygatt", "gattlib", "gattool", "bluepy" or "bluegiga"')
args = arg_parser.parse_args()

#--------------------------------------------------------------------------

class HubData(object):
    def __init__(self, hub_id):
        self.hub_id = hub_id
        self.hub = None
        self.label = None
        self.buttons = {}
        self.motor_powers = {}
        self.motors = {}

    def add_motor_button(self, button, port_name, action):
        self.buttons[get_motor_button_name(port_name, action)] = button
        self.motor_powers[port_name] = DEFAULT_SPEED

    def get_motor(self, motor_name):
        assert(self.hub is not None)
        if motor_name not in self.motors or not self.motors[motor_name]:
            self.motors[motor_name] = self.hub.get_device_by_port_name(motor_name)
        return self.motors[motor_name]

#--------------------------------------------------------------------------

def get_hub_data(hub_id):
    if hub_id in HUB_IDS:
        global hub_datas
        return hub_datas[hub_id]
    else:
        raise RuntimeError("Unexpected hub id: %s" % hub_id)
    return None

def get_motor_button_name(motor_name, action):
    return motor_name + "_" + action

#--------------------------------------------------------------------------

def hub_connect(conn_module_name, hub_id):
    used_hub_macs = []
    for hi in HUB_IDS:
        hd = get_hub_data(hi)
        if hd is None or hd.hub is None: continue
        used_hub_macs.append(hd.hub.address())

    conn = get_connection_by_name(conn_module_name, controller='hci0', hub_name=HUB_NAMES[HubType.TECHNIC_HUB], prohibited_hub_mac=used_hub_macs, reset=(not len(used_hub_macs)))
    assert(conn is not None)
    hub = TechnicHub(connection=conn)
    assert(hub.check_hub_type())

    hub_data = get_hub_data(hub_id)
    assert(hub_data is not None)

    hub_data.hub = hub
    hub_data.label['text'] = 'Hub %s: %s' % (hub_id, hub.address())
    for button_name in hub_data.buttons:
        if button_name.startswith("connect"):
            hub_data.buttons[button_name]['state'] = tk.DISABLED
        else:
            hub_data.buttons[button_name]['state'] = tk.NORMAL

def hub_disconnect(hub_id):
    hub_data = get_hub_data(hub_id)
    assert(hub_data is not None)
    if hub_data.hub is None: return

    hub_data.hub.disconnect()
    hub_data.hub = None
    hub_data.label['text'] = 'Hub '+hub_id+': N/A'
    for button_name in hub_data.buttons:
        if button_name.startswith("connect"):
            hub_data.buttons[button_name]['state'] = tk.NORMAL
        else:
            hub_data.buttons[button_name]['state'] = tk.DISABLED

def motor_start(hub_id, motor_name):
    hub_data = get_hub_data(hub_id)
    assert(hub_data is not None)
    motor = hub_data.get_motor(motor_name)
    if motor is None: return
    motor.set_power(power_primary=hub_data.motor_powers[motor_name])

def motor_stop(hub_id, motor_name):
    hub_data = get_hub_data(hub_id)
    assert(hub_data is not None)
    motor = hub_data.get_motor(motor_name)
    if motor is None: return
    #hub_data.motor_powers[motor_name] = 0
    motor.stop()

def motor_up(hub_id, motor_name):
    hub_data = get_hub_data(hub_id)
    assert(hub_data is not None)
    motor = hub_data.get_motor(motor_name)
    if motor is None: return
    hub_data.motor_powers[motor_name] = min(hub_data.motor_powers[motor_name]+SPEED_CHANGE, MAX_SPEED)
    motor.set_power(power_primary=hub_data.motor_powers[motor_name])
    time.sleep(HUB_DELAY)

def motor_down(hub_id, motor_name):
    hub_data = get_hub_data(hub_id)
    assert(hub_data is not None)
    motor = hub_data.get_motor(motor_name)
    if motor is None: return
    hub_data.motor_powers[motor_name] = max(hub_data.motor_powers[motor_name]-SPEED_CHANGE, -MAX_SPEED)
    motor.set_power(power_primary=hub_data.motor_powers[motor_name])
    time.sleep(HUB_DELAY)

#--------------------------------------------------------------------------

def connect(conn_module_name, hub_id):
    hub_data = get_hub_data(hub_id) 
    assert(hub_data is not None)  
    hub_data.buttons["connect"].after(DELAY, lambda: hub_connect(conn_module_name, hub_id))

def disconnect(hub_id):
    hub_data = get_hub_data(hub_id) 
    assert(hub_data is not None)  
    hub_data.buttons["disconnect"].after(DELAY, lambda: hub_disconnect(hub_id))

def motor_action(hub_id, motor_name, action):
    hub_data = get_hub_data(hub_id) 
    assert(hub_data is not None)
    button_name = get_motor_button_name(motor_name, action)
    assert(button_name in hub_data.buttons)
    hub_data.buttons[button_name].after(DELAY, eval("lambda: motor_"+action+"('"+hub_id+"','"+motor_name+"')"))

#--------------------------------------------------------------------------

hub_datas = {}
for hub_id in HUB_IDS:
    hub_datas[hub_id] = HubData(hub_id)

root = tk.Tk()
root.title("Lego Liebherr-9800 Control")

num_grid_cols = len(HUB_IDS)
num_grid_rows = 3 + max([len(hub_ports) for hub_ports in HUB_PORTS]) * len(MOTOR_ACTIONS)
root.geometry(str(BUTTON_WIDTH * num_grid_cols + HOR_MARGIN * (num_grid_cols+1)) + "x" + str(BUTTON_HEIGHT * num_grid_rows + VER_MARGIN * (num_grid_rows+1)))

for col_idx, hub_id in enumerate(HUB_IDS):
    hub_data = get_hub_data(hub_id)
    assert(hub_data is not None)

    pos_x = HOR_MARGIN + (BUTTON_WIDTH + HOR_MARGIN) * col_idx
    pos_y = VER_MARGIN

    hub_data.label = tk.Label(root, fg=LABEL_COLORS[hub_id], text='Hub '+hub_id+': N/A')
    hub_data.label.place(x=pos_x, y=pos_y, width=BUTTON_WIDTH, height=BUTTON_HEIGHT)
    pos_y += VER_MARGIN + BUTTON_HEIGHT

    f_name = 'connect_'+hub_id
    f_code = compile('def '+f_name+'(): return connect("'+args.connection+'", "'+hub_id+'")', "<string>", "exec")
    cmd = FunctionType(f_code.co_consts[0], globals(), f_name)
    button = tk.Button(root, text='Connect Hub', width=BUTTON_WIDTH, command=cmd)
    button.place(x=pos_x, y=pos_y, width=BUTTON_WIDTH, height=BUTTON_HEIGHT)
    hub_data.buttons["connect"] = button
    pos_y += VER_MARGIN + BUTTON_HEIGHT

    f_name = 'disconnect_'+hub_id
    f_code = compile('def '+f_name+'(): return disconnect("'+hub_id+'")', "<string>", "exec")
    cmd = FunctionType(f_code.co_consts[0], globals(), f_name)
    button = tk.Button(root, text='Disconnect Hub', width=BUTTON_WIDTH, command=cmd, state=tk.DISABLED)
    button.place(x=pos_x, y=pos_y, width=BUTTON_WIDTH, height=BUTTON_HEIGHT)
    hub_data.buttons["disconnect"] = button
    pos_y += VER_MARGIN + BUTTON_HEIGHT

    for port_idx, port_name in enumerate(HUB_PORTS[hub_id]):
        for action in MOTOR_ACTIONS:
            f_name = 'motor_'+hub_id+'_'+action
            f_code = compile('def '+f_name+'(): return motor_action("'+hub_id+'", "'+port_name+'", "'+action+'")', "<string>", "exec")
            cmd = FunctionType(f_code.co_consts[0], globals(), f_name)
            button = tk.Button(root, text=HUB_PORT_FUNCS[hub_id][port_idx] + ': ' + action, width=BUTTON_WIDTH, command=cmd, state=tk.DISABLED)
            button.place(x=pos_x, y=pos_y, width=BUTTON_WIDTH, height=BUTTON_HEIGHT)
            hub_data.add_motor_button(button, port_name, action)
            pos_y += VER_MARGIN + BUTTON_HEIGHT

root.mainloop()