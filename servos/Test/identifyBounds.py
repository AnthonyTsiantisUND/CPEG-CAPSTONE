from time import sleep
from adafruit_servokit import ServoKit

menu = """
A: Increase servo by 10 Degrees
D: Decrease servo by 10 Degrees
Q: Quit
"""

kit = ServoKit(channels=16)
kit.servo[6].angle = 180
curr_pos = 180
while True:
    servo = 0#int(input("Enter servo ID: "))
    print(menu)
    movement = input("$ ")
    
    if movement.lower() == "q":
        break
    
    if movement.lower() == "a":
        curr_pos += 10
        kit.servo[servo].angle = curr_pos
            
    elif movement.lower() == "d":
        curr_pos -= 10
        kit.servo[servo].angle = curr_pos
    else:
        print(f"Invalid input {movement}")
        
    print(f"Current Position: {curr_pos}")
    
    sleep(0.5)