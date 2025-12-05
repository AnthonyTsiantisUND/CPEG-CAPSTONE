from time import sleep
from adafruit_servokit import ServoKit

class Servo:
    def __init__(self, name, pca_id, default_pos, curr_pos, start_deg, end_deg):
        # Identification
        self.name = name
        self.pca_id = pca_id
        # Positions
        self.default_pos = default_pos
        self.curr_pos = curr_pos
        # Bounds
        self.start_deg = start_deg
        self.end_deg = end_deg
    
    def within_bounds(self, new_pos):
        # Make sure we are not moving servo beyond its own bounds
        if new_pos >= self.endDeg or new_pos <= self.startDeg:
            print(f"Failed to move servo to {new_pos}. Not within bounds [{self.startDeg}, {self.endDeg}].")
            return False
        return True

class Arm():
    def __init__(self):
        #                             Servo(name, pcaID, defaultPosition, startDeg, endDeg)
        self.thumb_lat              = Servo("Thumb Lateral", 0, 90, 0, 180)
        self.thumb_bottom_joint     = Servo("Thumb Bottom Joint", 1, 0, 0, 180)
        self.pointer_lat            = Servo("Pointer Lateral", 2, 90, 75, 105)
        self.pointer_bottom_joint   = Servo("Pointer Bottom Joint", 3, 0, 0, 180)
        self.pointer_top_joint      = Servo("Pointer Bottom Joint", 4, 0, 0, 180)
        # self.middle_lat           = Servo("Middle Lateral", 5, 90, 75, 105)
        self.middle_bottom_joint    = Servo("Middle Bottom Joint", 6, 0, 0, 180)
        self.middle_top_joint       = Servo("Middle Bottom Joint", 7, 0, 0, 180)
        # self.ring_lat             = Servo("Ring Lateral", 8, 90, 75, 105)
        self.ring_bottom_joint      = Servo("Ring Bottom Joint", 9, 0, 0, 180)
        self.ring_top_joint         = Servo("Ring Bottom Joint", 10, 0, 0, 180)
        # self.pinkie_lat           = Servo("Pinkie Lateral", 11, 90, 75, 105)
        self.pinkie_bottom_joint    = Servo("Pinkie Bottom Joint", 12, 0, 0, 180)
        self.pinkie_top_joint       = Servo("Pinkie Bottom Joint", 13, 0, 0, 180)
        # self.top_wrist            = Servo("Top Wrist", 14, X, X, X)
        # self.bottom_wrist         = Servo("Bottom Wrist", 15, X, X, X)
    
        self.arm = [
            thumb_lat, 
            thumb_bottom_joint, 
            pointer_lat,
            pointer_bottom_joint,
            pointer_top_joint,
            #middle_lat,
            middle_bottom_joint,
            middle_top_joint,
            #ring_lat,
            ring_bottom_joint,
            ring_top_joint,
            #pinkie_lat,
            pinkie_bottom_joint,
            pinkie_top_joint,
            #top_wrist,
            #bottom_wrist
        ]
        self.kit = kit = ServoKit(channels=16)

    def valid_movement(self, servo_id, new_pos):
        # Validate within servo's own bounds
        if not self.arm[servo_id].within_bounds(new_pos):
            return False
        
        # Pointer lat
        degrees_of_freedom = 20
        if servo_id == 2:
            # Pointer lateral movement is limited to the left, but not the right
            if new_pos - self.arm[5].currPos < degrees_of_freedom:
                print("Cannot move pointer finger as middle finger is too close")
                return False
            return True

        # Middle Lat
        elif servo_id == 5:
            # Middle lateral movement is restricted by pointer and ring
            if abs(self.arm[2].currPos - new_pos) < degrees_of_freedom and \
               abs(self.arm[8].currPos - new_pos) < degrees_of_freedom:
               return True
            elif abs(self.arm[2].currPos - new_pos) < degrees_of_freedom:
                print("Cannot move middle lat as ring finger is too close")
            elif abs(self.arm[8].currPos - new_pos) < degrees_of_freedom:
                print("Cannot move middle lat as pointer finger is too close")
            else:
                print("Cannot move middle lat as pointer and ring fingers are too close")
            return False
                
        # Ring Lat
        elif servo_id == 8:
            # Middle lateral movement is restricted by pointer and ring
            if abs(self.arm[5].currPos - new_pos) < degrees_of_freedom and \
               abs(self.arm[11].currPos - new_pos) < degrees_of_freedom:
               return True
            elif abs(self.arm[5].currPos - new_pos) < degrees_of_freedom:
                print("Cannot move ring lat as pinkie finger is too close")
            elif abs(self.arm[11].currPos - new_pos) < degrees_of_freedom:
                print("Cannot move ring lat as middle finger is too close")
            else:
                print("Cannot move ring lat as middle and pinkie fingers are too close")
            return False
            
        # Pinkie Lat
        elif servo_id == 11:
            # Pinkie lateral movement is limited to the right, but not the left
            if new_pos - self.arm[8].currPos < degrees_of_freedom:
                print("Cannot move pointer finger as middle finger is too close")
                return False
            return True

    def set_servo_pos(self, servo_id, new_pos):
        if not valid_movement(servo_id, new_pos):
            return
        
        self.arm[servo_id].curr_pos = new_pos
        self.kit[servo_id].angle = new_pos
        print(f"Moved {self.arm[servo_id].name} to {new_pos}")
        # sleep(0.25)

    
    def neutral_position(self):
        for servo in self.arm:
            self.set_servo_pos(servo.pca_id, servo.default_pos)

    def closed_fist(self):
        self.neutral_position()
        # Move all fingers to full closed position
        for servo_id in [1, 3, 4, 6, 7, 9, 10, 12, 13]:
            self.arm.set_servo_pos(servo_id, 180)

menu = \
"""
Select an action
1) Reset to neutral
2) Closed fist
3) Quit
"""
arm = Arm()
while True:
    print(menu)
    choice = int(input("$ "))
    if choice == 1:
        arm.neutral_position()
    elif choice == 2:
        arm.closed_fist()
    elif choice == 3:
        break
    else:
        print("Invalid selection")