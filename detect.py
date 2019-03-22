print "Booting python script..."

import RPi.GPIO as GPIO
import time
import datetime
import sys

from firebase import firebase
from config import *
from subprocess import check_output

# Internet connectivity
try:
    import httplib
except:
    import http.client as httplib

# Util functions
current_milli_time = lambda: int(round(time.time() * 1000))

class Device():

    def __init__(self, name=None, pin=None, machinetype=None, paymenttype=None):
        self.pin = pin
        self.state = LIGHT_OFF
        self.machinetype = machinetype
        self.paymenttype = paymenttype
        self.name = name

        # These two vars measure the number of times an ON or OFF was detected in the last ON_OFF_COUNT_INTERVAL_SEC
        self.num_on = 0
        self.num_off = 0

    def callback(self, pin):
        # For some reason, adding a sleep causes the reading to be more reliable
        time.sleep(0.01)

        # Get and invert reading
        reading = 1 - GPIO.input(self.pin)
        if reading == LIGHT_ON:
            self.num_on += 1
        else:
            self.num_off += 1
        
        print str(self)

    def compute_and_reset_state(self):
        # This is called to get the current state of the sensor right before sending it to Firebase
        reading = 1 - GPIO.input(self.pin)
    
        # If we have received a certain number of interrupts for on AND off - we are blinking
        if self.num_on > ON_OFF_COUNT_BLINK_THRESHOLD and self.num_off > ON_OFF_COUNT_BLINK_THRESHOLD:
            self.state = LIGHT_BLINKING
        else:
            # If not - we just take the latest reading from the sensor as the state
            self.state = reading
        # Output to test LED if the correct pin is activated 
        #if self.pin == TEST_GPIO_PIN:
        #    print "Setting GPIO output to " + str(reading)
        #    GPIO.output(LED_PIN, self.state)

        # Reset on/off count
        self.num_on = 0
        self.num_off = 0
        return self.state

        
    def __str__(self):
        return "Device: name - " + str(self.name) + ", pin - " + str(self.pin) + ", state - " + str(self.state) + " - num_on: " + str(self.num_on) + " num_off: " + str(self.num_off)
    
    def get_status_string(self):
        status_string = "unknown"
        if self.state == LIGHT_BLINKING:
            status_string = "blinking"
        elif self.state == LIGHT_OFF:
            status_string = "off"
        else:
            status_string = "on"
        return status_string



def setup_devices_gpio(devices):
    # Use BCM Mode
    GPIO.setmode(GPIO.BCM)

    # Set all relevant pins as input, pull down to 0V to have standard washing machine status as off
    # Note for the button case - this has to be PUD_UP
    for device in devices:
        GPIO.setup(device.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(device.pin, GPIO.BOTH, callback=device.callback, bouncetime=BOUNCETIME) 

    #GPIO.setup(LED_PIN, GPIO.OUT)

def exception_handler(request, exception):
    print "For request: " + str(request) + " got exception: " + str(exception)


def response_callback(response):
    print response

def have_internet():
    conn = httplib.HTTPConnection("www.google.com", timeout=5)
    try:
        conn.request("HEAD", "/")
        conn.close()
        return True
    except:
        conn.close()
        return False

def get_pi_serial():
    # Extract serial from cpuinfo file
    try:
        with open('/proc/cpuinfo','r') as f:
            for line in f:
                if line[0:6] == 'Serial':
                    cpuserial = line[10:26]
                    return cpuserial
    except:
        return None

if __name__ == "__main__":
    try:
        PI_DEVICE_ID
    except NameError:
        PI_DEVICE_ID = None
    
    if not PI_DEVICE_ID:
        # Use Raspberry Pi's CPU serial number if config.py does not set an ID
        PI_DEVICE_ID = get_pi_serial() or "dev-non-pi"
    
        while not have_internet():
            print "Waiting for internet to come online..."
            time.sleep(1)
            #print "No connection.. exiting.. supervisor please restart me."
            #sys.exit(1)
            
        print "Initializing Firebase connection"
        # Open up network conn to Firebase
        firebase = firebase.FirebaseApplication('https://tlaundry2.firebaseio.com', None)
        print "Firebase connection set up."

        print "Starting async firebase get"

        # Initialize washers and dryers
        DEVICES = [Device(**washer) for washer in WASHERS]
        DEVICES += [Device(**dryer) for dryer in DRYERS]

        setup_devices_gpio(DEVICES)

        # Begin main timer loop
        while True:

            try:
                # Sleep until we want to check the current washer state
                time.sleep(ON_OFF_COUNT_INTERVAL_SEC)
                # Go through all the washers and check the state
                current_state = {}
                current_state["timestamp"] = datetime.datetime.now().isoformat()
                for device in DEVICES:
                    device_state = device.compute_and_reset_state()
                    current_state[str(device.name)] =  device.get_status_string()

                print str(current_state)

                current_state["ip-"+PI_DEVICE_ID] = check_output(['hostname', '-I'])

                result = firebase.patch_async('/'+FLOOR_NUMBER, current_state, callback=response_callback)

            except Exception as e:
                print "Exception msg: " + str(e.message) + " args = " + str(e.args)
