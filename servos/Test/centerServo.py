import time
from adafruit_servokit import ServoKit

kit = ServoKit(channels=16)

for i in range(16):
    # Palm [0-4] and Wrist [14, 15] Servos
    if i < 5 or i > 13:
        kit.servo[i].angle = 90
    else: # Forearm Servos [5-13]
        kit.servo[i].angle = 0

