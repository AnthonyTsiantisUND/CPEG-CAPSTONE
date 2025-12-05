import asyncio
import numpy as np
import joblib
import cv2
import os
from bleak import BleakClient
import sys
print("RUNNING FILE:", sys.argv[0])


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

M1_ADDR = "88:13:BF:14:F7:1E"
M2_ADDR = "88:13:BF:13:67:56"
CHAR_UUID = "f3a56edf-8f1e-4533-93bf-5601b2e91308"

WINDOW_SIZE = 50
STEP_SIZE = 10
USE_PCA = False  # IMPORTANT: PCA must be disabled
PREDICTION_SMOOTH_WINDOW = 5

CLASS_TO_IMAGE = {
    "flat_hand": "3DIMG/flat_hand.png",
    "closed_fist": "3DIMG/closed_fist.png",
    "pinch": "3DIMG/pinch.png"
}

print("\nLoading ML pipeline...\n")
scaler = joblib.load("ML/scaler.pkl")
model = joblib.load("ML/best_svm_model.pkl")
print("\nModels loaded.\n")


# ------------------------------------------------------------
# FEATURE EXTRACTION
# ------------------------------------------------------------

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
    # EXACT 8 FEATURES PER SENSOR → 16 TOTAL
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

    print("LIVE FEATURE COUNT =", combined.shape[1])
    return combined


# ------------------------------------------------------------
# BLE STREAMING HANDLER
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# CLASSIFICATION
# ------------------------------------------------------------

prediction_history = []

def classify(win1, win2):
    x = window_to_vector(win1, win2)

    # SCALE ONLY — PCA IS NOT USED IN THE TRAINED MODEL
    x = scaler.transform(x)

    print("AFTER SCALER SHAPE =", x.shape)

    pred = model.predict(x)[0]

    prediction_history.append(pred)
    if len(prediction_history) > PREDICTION_SMOOTH_WINDOW:
        prediction_history.pop(0)

    values, counts = np.unique(prediction_history, return_counts=True)
    smoothed = values[np.argmax(counts)]
    return smoothed


# ------------------------------------------------------------
# IMAGE DISPLAY
# ------------------------------------------------------------

current_image_class = None

def show_prediction_image(pred_class):
    global current_image_class
    if pred_class == current_image_class:
        return

    current_image_class = pred_class
    path = CLASS_TO_IMAGE.get(pred_class)

    if not path or not os.path.exists(path):
        print(f"[WARNING] No image found for class '{pred_class}' at {path}")
        return

    img = cv2.imread(path)
    cv2.imshow("Predicted Motion", img)
    cv2.waitKey(1)


# ------------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------------

async def run_live():
    print("Connecting to MyoWare sensors...\n")

    async with BleakClient(M1_ADDR) as c1, BleakClient(M2_ADDR) as c2:
        await c1.start_notify(CHAR_UUID, M1.handle)
        await c2.start_notify(CHAR_UUID, M2.handle)

        print("Connected! Streaming + classifying...\n")
        last_step = 0

        while True:
            w1 = M1.get_window()
            w2 = M2.get_window()

            if w1 and w2:
                if len(M1.buffer) - last_step >= STEP_SIZE:
                    last_step = len(M1.buffer)
                    pred = classify(w1, w2)
                    print("prediction:", pred)
                    show_prediction_image(pred)

            await asyncio.sleep(0.01)


if __name__ == "__main__":
    try:
        asyncio.run(run_live())
    except KeyboardInterrupt:
        print("\nStopping.")
        cv2.destroyAllWindows()
