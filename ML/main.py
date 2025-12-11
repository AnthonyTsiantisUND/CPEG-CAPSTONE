from time import sleep
from adafruit_servokit import ServoKit
from PIL import Image
import os

def show_image(path):
    if not os.path.exists(path):
        print(f"image not found at {path}")
        return
    try:
        img = Image.open(path)
        img.show()
        print(f"showing image at {path}")
    except Exception as e:
        print(f"could not display image --> {e}")
class Servo:
    def __init__(self, name, pca_id, default_pos, start_deg, end_deg):
        # Identification
        self.name = name
        self.pca_id = pca_id
        # Positions
        self.default_pos = default_pos
        self.curr_pos = default_pos
        # Bounds
        self.start_deg = start_deg
        self.end_deg = end_deg
    
    def within_bounds(self, new_pos):
        # Make sure we are not moving servo beyond its own bounds
        if new_pos > self.end_deg or new_pos < self.start_deg:
            print(f"Failed to move servo to {new_pos}. Not within bounds [{self.start_deg}, {self.end_deg}].")
            return False
        return True

class Arm():
    def __init__(self):
        #                             Servo(name, pcaID, defaultPosition, start_deg, end_deg)
        self.thumb_lat              = Servo("Thumb Lateral", 0, 80, 0, 160)
        self.thumb_bottom_joint     = Servo("Thumb Bottom Joint", 1, 0, 0, 180)
        self.pointer_lat            = Servo("Pointer Lateral", 2, 60, 0, 110)
        self.pointer_bottom_joint   = Servo("Pointer Bottom Joint", 3, 0, 0, 180)
        self.pointer_top_joint      = Servo("Pointer Bottom Joint", 4, 0, 0, 180)
        self.middle_lat           = Servo("Middle Lateral", 5, 60, 10, 110)
        self.middle_bottom_joint    = Servo("Middle Bottom Joint", 6, 180, 0, 180) # Accidentally wired this backwards so 180 is open and 0 is closed
        self.middle_top_joint       = Servo("Middle Bottom Joint", 7, 0, 0, 180)
        self.ring_lat             = Servo("Ring Lateral", 8, 90, 75, 130)
        self.ring_bottom_joint      = Servo("Ring Bottom Joint", 9, 0, 0, 180)
        self.ring_top_joint         = Servo("Ring Bottom Joint", 10, 0, 0, 180)
        self.pinkie_lat           = Servo("Pinkie Lateral", 11, 60, 40, 100)
        self.pinkie_bottom_joint    = Servo("Pinkie Bottom Joint", 12, 0, 0, 180)
        self.pinkie_top_joint       = Servo("Pinkie Bottom Joint", 13, 0, 0, 180)
        self.top_wrist            = Servo("Top Wrist", 14, 100, 100, 150)
        self.bottom_wrist         = Servo("Bottom Wrist", 15, 90, 60, 120)
    
        self.arm = [
            self.thumb_lat, 
            self.thumb_bottom_joint, 
            self.pointer_lat,
            self.pointer_bottom_joint,
            self.pointer_top_joint,
            self.middle_lat,
            self.middle_bottom_joint,
            self.middle_top_joint,
            self.ring_lat,
            self.ring_bottom_joint,
            self.ring_top_joint,
            self.pinkie_lat,
            self.pinkie_bottom_joint,
            self.pinkie_top_joint,
            self.top_wrist,
            self.bottom_wrist
        ]
        
        self._images = {
            "spock": "../3DIMG/spock.png",
            "closed_fist": "3DIMG/closed_fist.png",
            "flat_hand":"../3DIMG/flat_hand.png",
            "middle_down":"../3DIMG/middle_down.png",
            "pointer_down":"../3DIMG/one_finger_out.png",
            "peace":"../3DIMG/peace.png",
            "pinky_down":"../3DIMG/pinky_down.png",
            "ring_down":"../3DIMG/ring_down.png",
            "rock_and_roll":"../3DIMG/rock_and_roll.png",
            "thumb_down":"../3DIMG/thumb_down.png",
            "the_bird":"../3DIMG/bird.png"
            }
            
        self.kit = kit = ServoKit(channels=16)
        
        # Set hand to default positioning
        for i in range(16):
            self.kit.servo[i].angle = self.arm[i].default_pos

    def set_servo_pos(self, servo_id, new_pos):
        if not self.arm[servo_id].within_bounds(new_pos):
            return
        
        self.arm[servo_id].curr_pos = new_pos
        self.kit.servo[servo_id].angle = new_pos
        print(f"Moved {self.arm[servo_id].name} to {new_pos}")
        # sleep(0.25)
        
    def reset_lats(self):
        self.set_servo_pos(0, self.arm[0].default_pos) # Thumb
        self.set_servo_pos(2, self.arm[2].default_pos) # Pointer
        self.set_servo_pos(5, self.arm[5].default_pos) # Middle
        self.set_servo_pos(8, self.arm[8].default_pos) # Ring
        self.set_servo_pos(11, self.arm[11].default_pos) # Pinkie
    
    def spock(self):
        show_image(self._images["spock"])
        self.set_servo_pos(2, 30) # Pointer
        self.set_servo_pos(5, 30) # Middle
        self.set_servo_pos(8, 130) # Ring
        self.set_servo_pos(11, 90) # Pinkie

    def close_pointer_finger(self):
        self.set_servo_pos(3, 180)
        self.set_servo_pos(4, 180)

    def close_middle_finger(self):
        self.set_servo_pos(6, 0)
        self.set_servo_pos(7, 180)

    def close_ring_finger(self):
        self.set_servo_pos(9, 180)
        self.set_servo_pos(10, 180)

    def close_pinkie_finger(self):
        self.set_servo_pos(12, 180)
        self.set_servo_pos(13, 180)

    def close_thumb(self):
        self.set_servo_pos(1, 180)

    def open_pointer_finger(self):
        self.set_servo_pos(3, 0)
        self.set_servo_pos(4, 0)

    def open_middle_finger(self):
        self.set_servo_pos(6, 180)
        self.set_servo_pos(7, 0)

    def open_ring_finger(self):
        self.set_servo_pos(9, 0)
        self.set_servo_pos(10, 0)

    def open_pinkie_finger(self):
        self.set_servo_pos(12, 0)
        self.set_servo_pos(13, 0)

    def open_thumb(self):
        self.set_servo_pos(1, 0)


    def reset(self):
        for servo in self.arm:
            self.set_servo_pos(servo.pca_id, servo.default_pos)
        
    def close_fist(self):
        show_image(self._images["closed_fist"])
        self.close_pointer_finger()
        self.close_middle_finger()
        self.close_ring_finger()
        self.close_pinkie_finger()
        self.close_thumb()
        
    def left_right_wave(self):
        # Tilt wrist down slightly
        self.set_servo_pos(14, 120)
        
        # Wave left to right a few times
        self.set_servo_pos(15, 80)
        sleep(1)
        for _ in range(5):
            for i in range(60, 121, 10):
                self.set_servo_pos(15, i)
                sleep(0.05)
            
            for i in range(120, 59, -10):
                self.set_servo_pos(15, i)
                sleep(0.05)
        
        # Reset to center
        self.set_servo_pos(15, self.arm[15].default_pos)
        sleep(1)
        
        # Reset wrist and lats
        self.set_servo_pos(14, self.arm[14].default_pos)
        self.reset_lats()
        
    def top_down_wave(self):
        # Tilt wrist down slightly
        self.set_servo_pos(14, self.arm[14].default_pos)
        for _ in range(5):
            for i in range(self.arm[14].default_pos, self.arm[14].end_deg+1, 10):
                self.set_servo_pos(14, i)
                sleep(0.05)
            
            for i in range(self.arm[14].end_deg, self.arm[14].default_pos+1, -10):
                self.set_servo_pos(14, i)
                sleep(0.05)
        
        self.set_servo_pos(14, self.arm[14].default_pos)
    
    def the_bird(self):
        self.close_pinkie_finger()
        self.close_ring_finger()
        self.close_pointer_finger()
        self.close_thumb()
    
    def peace(self):
        self.close_pinkie_finger()
        self.close_ring_finger()
        self.close_thumb()
        
menu = \
"""
Select an action
1) Reset Lats
2) Spock
3) Reset Everything
4) Close Thumb
5) Open Thumb
6) Close Pointer Finger
7) Open Pointer Finger
8) Close Middle Finger
9) Open Middle Finger
10) Close Ring Finger
11) Open Ring Finger
12) Close Pinkie Finger
13) Open Pinkie Finger
14) Close fist
15) Left/Right Wave
16) Top/Down Wave
17) The Bird
18) Peace
19) Quit
"""
arm = Arm()
while True:
    print(menu)
    choice = int(input("$ "))
    if choice == 1:
        arm.reset_lats()
    elif choice == 2:
        arm.spock()
    elif choice == 3:
        arm.reset()
    elif choice == 4:
        arm.close_thumb()
    elif choice == 5:
        arm.open_thumb()  
    elif choice == 6:
        arm.close_pointer_finger()
    elif choice == 7:
        arm.open_pointer_finger()
    elif choice == 8:
        arm.close_middle_finger()
    elif choice == 9:
        arm.open_middle_finger()
    elif choice == 10:
        arm.close_ring_finger()
    elif choice == 11:
        arm.open_ring_finger()
    elif choice == 12:
        arm.close_pinkie_finger()
    elif choice == 13:
        arm.open_pinkie_finger()
    elif choice == 14:
        arm.close_fist()
    elif choice == 15:
        arm.left_right_wave()
    elif choice == 16:
        arm.top_down_wave()
    elif choice == 17:
        arm.the_bird()
    elif choice == 18:
        arm.peace()
    elif choice == 19:
        break
    else:
        print("Invalid selection")