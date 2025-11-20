from time import sleep
from adafruit_servokit import ServoKit

class Servo:
    def __init__(self, kit, name, pcaID, position, startDeg, endDeg):
        self.kit = kit
        self.name = name
        self.pcaID = pcaID
        self.position = position
        self.startDeg = startDeg
        self.endDeg = endDeg
    
    def update_pos(self, new_pos):
        # Make sure position is within bounds
        if new_pos > self.endDeg or new_pos < self.startDeg:
            print(f"Failed to move servo to {new_pos}. Not within bounds [{self.startDeg}, {self.endDeg}].")
            return False
        
        print(f"Moving {self.name} (ID={self.pcaID}) to {new_pos}")
        self.kit.servo[self.pcaID].angle = new_pos
        self.position = new_pos
        sleep(0.5)
        print(f"{self.name} (ID={self.pcaID}) now at {new_pos}")
        return True
        
kit = ServoKit(channels=16)
pointerFingerBase = Servo(kit, "Pointer Finger Base", 1, 90, 0, 180)

topWrist = Servo(kit, "Top Wrist", 1, 90, 50, 150)

menu = """
A: Increase servo by 10 Degrees
D: Decrease servo by 10 Degrees
Q: Quit
"""

current_pos = 90
while True:
    print(menu)
    delta = input("$ ")
    if delta.lower() == "a":
        current_pos += 10
    elif delta.lower() == "d":
        current_pos -= 10
    elif delta.lower() == "q":
        break
    
    print(current_pos)
    
    kit.servo[4].angle = current_pos
    sleep(1)