from time import sleep
from adafruit_servokit import ServoKit

menu = """
A: Increase servo by 10 Degrees
D: Decrease servo by 10 Degrees
Q: Quit
"""

kit = ServoKit(channels=16)
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