import pigpio, time

pi = pigpio.pi()
pin = 17 # Physical pin 11

if not pi.connected:
    raise SystemExit("Pigpoid not running")

def move(pulse):
    pi.set_servo_pulsewidth(pin, pulse)
    print(f"Pulse: {pulse} microsec")
    time.sleep(1.5)

# Code for a full 180 deg rotation
'''
pi.set_servo_pulsewidth(pin, 500)
time.sleep(5)

for pulse in range(500, 2501, 25):
    pi.set_servo_pulsewidth(pin, pulse)
    print(pulse)
    time.sleep(0.05)
'''

'''
move(1250)
time.sleep(2)
move(1500)
time.sleep(2)
move(1750)
time.sleep(5)
move(1250)
time.sleep(2)
move(1500)
time.sleep(2)
move(1750)
'''

print("Centering...")
move(1500)

print("Left (0 deg approx)...")
move(500)

print("Center...")
move(1500)

print("Right (180 deg approx)...")
move(2500)

print("Return to Center...")
move(1500)

pi.set_servo_pulsewidth(pin, 0)
pi.stop()