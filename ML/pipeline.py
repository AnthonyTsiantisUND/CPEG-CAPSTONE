import asyncio
import sys
import os
from time import sleep

import numpy as np
import joblib
from bleak import BleakClient
from adafruit_servokit import ServoKit

# ------------------------------------------------------------
# Optional: Windows event loop fix (safe on Pi/Linux too)
# ------------------------------------------------------------
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Import servo file
target_dir = os.path.abspath("../servos/")
if target_dir not in sys.path:
    sys.path.append(target_dir)
    

import main
# ============================================================
#                ML + BLE LIVE STREAMING MODE
# ============================================================

# BLE / ML config
M1_ADDR = "88:13:BF:14:F7:1E"
M2_ADDR = "88:13:BF:13:67:56"
CHAR_UUID = "f3a56edf-8f1e-4533-93bf-5601b2e91308"

WINDOW_SIZE = 50
STEP_SIZE = 10

# lazy-load ML so menu mode doesn't break if ML files absent
_scaler = None
_model = None

def load_ml():
    global _scaler, _model
    if _scaler is None or _model is None:
        print("\nLoading ML pipeline...\n")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        _scaler = joblib.load(os.path.join(base_dir,"scaler.pkl"))
        _model = joblib.load(os.path.join(base_dir,"best_svm_model.pkl"))
        print("Models loaded.\n")
    return _scaler, _model


def compute_features(signal):
    s = np.asarray(signal, dtype=float)
    return {
        "rms": np.sqrt(np.mean(s ** 2)),
        "mean_abs": np.mean(np.abs(s)),
        "waveform_length": np.sum(np.abs(np.diff(s))),
        "zero_cross": np.sum(np.diff(np.sign(s)) != 0),
        "slope_changes": np.sum(np.diff(np.sign(np.diff(s))) != 0),
        "var": np.var(s),
        "std": np.std(s),
        "max": np.max(s),
    }


def window_to_vector(win1, win2):
    keys = [
        "rms",
        "mean_abs",
        "waveform_length",
        "zero_cross",
        "slope_changes",
        "var",
        "std",
        "max"
    ]
    f1 = compute_features(win1)
    f2 = compute_features(win2)

    v1 = np.array([f1[k] for k in keys])
    v2 = np.array([f2[k] for k in keys])
    combined = np.concatenate([v1, v2]).reshape(1, -1)
    return combined


class EMGStream:
    def __init__(self):
        self.buffer = []

    def handle(self, sender, data):
        try:
            text = data.decode(errors="ignore").strip()
            val = float(text)
            self.buffer.append(val)
        except:
            pass

    def get_window(self):
        if len(self.buffer) >= WINDOW_SIZE:
            return self.buffer[-WINDOW_SIZE:]
        return None


M1 = EMGStream()
M2 = EMGStream()

last_pred = None  # so we don't spam the same command over and over


def apply_prediction_to_arm(pred: str, arm: main.Arm()):
    """Map ML prediction to servo actions."""
    global last_pred
    if pred == last_pred:
        return  # avoid repeating the same action constantly
    last_pred = pred

    print(f"\n[ACTION] New prediction: {pred}\n")

    if pred == "flat_hand":
        arm.reset()
    elif pred == "closed_fist":
        arm.close_fist()
    else:
        print("[INFO] No servo action mapped for this label yet.")


async def live_stream_mode(arm: main.Arm()):
    scaler, model = load_ml()

    print("Connecting to MyoWare sensors...\n")
    async with BleakClient(M1_ADDR) as c1, BleakClient(M2_ADDR) as c2:
        await c1.start_notify(CHAR_UUID, M1.handle)
        await c2.start_notify(CHAR_UUID, M2.handle)

        print("Connected! Streaming + classifying...\n")
        last_step = 0

        try:
            while True:
                w1 = M1.get_window()
                w2 = M2.get_window()

                if w1 and w2:
                    if len(M1.buffer) - last_step >= STEP_SIZE:
                        last_step = len(M1.buffer)

                        x = window_to_vector(w1, w2)
                        x = scaler.transform(x)
                        pred = model.predict(x)[0]

                        print("prediction:", pred)
                        apply_prediction_to_arm(pred, arm)

                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            print("Live stream cancelled.")


# ============================================================
#                        MAIN ENTRY
# ============================================================

if __name__ == "__main__":
    print("""
=============================
   HAND CONTROL MAIN MENU
=============================
1) Live streaming mode (EMG → ML → servos)
2) Manual menu mode
=============================
""")

    choice = input("Select mode (1 or 2): ").strip()

    if choice == "1":
        try:
            asyncio.run(live_stream_mode(main.Arm()))
        except KeyboardInterrupt:
            print("\nStopping live mode.")
    elif choice == "2":
        main.run()
    else:
        print("Invalid mode. Exiting.")
