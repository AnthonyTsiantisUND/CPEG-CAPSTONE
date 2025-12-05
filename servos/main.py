from time import sleep
from adafruit_servokit import ServoKit

class Servo:
    def __init__(self, name, pcaID, position, startDeg, endDeg):
        self.name = name
        self.pcaID = pcaID
        self.position = position
        self.startDeg = startDeg
        self.endDeg = endDeg
    
    def within_bounds(self, new_pos):
        # Make sure position is within bounds
        if new_pos > self.endDeg or new_pos < self.startDeg:
            print(f"Failed to move servo to {new_pos}. Not within bounds [{self.startDeg}, {self.endDeg}].")
            return False
        return True
        
kit = ServoKit(channels=16)

# Servo(kit, name, pcaID, defaultPosition, startDeg, endDeg)

thumb_lat = Servo("Thumb Lateral", 0, 90, 0, 180)
pointer_lat = Servo("Pointer Lateral", 2, 90, 75, 105)

servos = [thumb_lat, "", pointer_lat]


menu = """
A: Increase servo by 10 Degrees
D: Decrease servo by 10 Degrees
Q: Quit
"""

while True:
    servo = 2#int(input("Enter servo ID: "))
    print(menu)
    movement = input("$ ")
    
    if movement.lower() == "q":
        break
    
    if movement.lower() == "a":
        if servos[servo].within_bounds(servos[servo].position + 10):
            kit.servo[servo].angle = servos[servo].position + 10
            servos[servo].position += 10
            
    elif movement.lower() == "d":
        if servos[servo].within_bounds(servos[servo].position - 10):
            kit.servo[servo].angle = servos[servo].position - 10
            servos[servo].position -= 10
    else:
        print(f"Invalid input {movement}")
        
    print(f"Servo {servos[servo].name} at {servos[servo].position}")
    
    sleep(1)