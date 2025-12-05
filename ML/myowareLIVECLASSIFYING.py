import asyncio
import numpy as np
import joblib
import cv2
import os
from bleak import BleakClient

# config

M1_ADDR = "88:13:BF:14:F7:1E"
M2_ADDR = "88:13:BF:13:67:56"
CHAR_UUID = "f3a56edf-8f1e-4533-93bf-5601b2e91308"

WINDOW_SIZE = 50
STEP_SIZE = 10
USE_PCA = True
PREDICTION_SMOOTH_WINDOW = 5  # majority vote mechanism

# image mapping
CLASS_TO_IMAGE = {
    "flat": "3DIMG/flat_hand.png",
    "fist": "3DIMG/closed_fist.png",
    "pinch": "3DIMG/pinch.png"
}

# load ML models
print("\nload in the ML pipeline\n")
scaler = joblib.load("ML/scaler.pkl")
model = joblib.load("ML/best_svm_model.pkl")
pca = joblib.load("ML/pca.pkl") if USE_PCA else None
print("\nmodels loaded in\n")

# feature extraction mechanisms
def compute_features(signal):
    s = np.asarray(signal, dtype=float)
    feats = {
        "rms": np.sqrt(np.mean(s ** 2)),
        "mean_abs": np.mean(np.abs(s)),
        "waveform_length": np.sum(np.abs(np.diff(s))),
        "zero_cross": np.sum(np.diff(np.sign(s)) != 0),
        "slope_changes": np.sum(np.diff(np.sign(np.diff(s))) != 0),
        "var": np.var(s),
        "std": np.std(s),
        "min": np.min(s),
        "max": np.max(s),
    }
    return feats

def window_to_vector(win1, win2):
    keys = ["rms", "mean_abs", "waveform_length", "zero_cross",
            "slope_changes", "var", "std", "min", "max"]

    f1 = compute_features(win1)
    f2 = compute_features(win2)

    v1 = np.array([f1[k] for k in keys])
    v2 = np.array([f2[k] for k in keys])

    combined = np.concatenate([v1, v2]).reshape(1, -1)
    return combined

# stream handler 

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

# streams for both sensors
M1 = EMGStream()
M2 = EMGStream()

# classifier mechanisms 
prediction_history = []

def classify(win1, win2):
    global prediction_history

    x = window_to_vector(win1, win2)
    x = scaler.transform(x)
    if USE_PCA:
        x = pca.transform(x)

    pred = model.predict(x)[0]

    # rolling majority vote
    prediction_history.append(pred)
    if len(prediction_history) > PREDICTION_SMOOTH_WINDOW:
        prediction_history.pop(0)

    values, counts = np.unique(prediction_history, return_counts=True)
    smoothed = values[np.argmax(counts)]
    return smoothed

# image printing 
current_shown_class = None

def show_prediction_image(predicted_class):
    """
    Shows the image corresponding to the predicted class in a window.
    Only refreshes window when class changes.
    """
    global current_shown_class
    if predicted_class == current_shown_class:
        return

    current_shown_class = predicted_class

    img_path = CLASS_TO_IMAGE.get(predicted_class)
    if img_path is None or not os.path.exists(img_path):
        print(f"[WARNING] No image for class '{predicted_class}'")
        return

    img = cv2.imread(img_path)
    if img is None:
        print(f"[ERROR] Failed to load image: {img_path}")
        return

    cv2.imshow("Predicted Motion", img)
    cv2.waitKey(1)

# main running loop!

async def run_live():
    print("connecting to myoware sensors.\n")

    async with BleakClient(M1_ADDR) as c1, BleakClient(M2_ADDR) as c2:
        # Start BLE notifications
        await c1.start_notify(CHAR_UUID, M1.handle)
        await c2.start_notify(CHAR_UUID, M2.handle)

        print("connected!!!! streaming & classifying now\n")

        last_step = 0

        while True:
            w1 = M1.get_window()
            w2 = M2.get_window()

            # need two good windows and step size
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
        print("\nStopping live classifier.")
        cv2.destroyAllWindows()
