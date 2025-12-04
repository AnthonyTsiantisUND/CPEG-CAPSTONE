import asyncio
import numpy as np
import joblib
from bleak import BleakClient

# -------------------------------
#  SENSOR CONFIG
# -------------------------------
M1_ADDR = "88:13:BF:14:F7:1E"
M2_ADDR = "88:13:BF:13:67:56"
CHAR_UUID = "f3a56edf-8f1e-4533-93bf-5601b2e91308"

WINDOW_SIZE = 50
STEP_SIZE = 10

# -------------------------------
#  LOAD MODELS (Your Directory!)
# -------------------------------
print("Loading models...")

scaler = joblib.load("ML/scaler.pkl")
model = joblib.load("ML/best_svm_model.pkl")

USE_PCA = False   # You do NOT have a PCA pickle
print("Loaded scaler + SVM.\n")


# -------------------------------
#  FEATURE EXTRACTION
# -------------------------------
def compute_features(signal):
    s = np.asarray(signal).astype(float)
    feats = {}
    feats["rms"] = np.sqrt(np.mean(s**2))
    feats["mean_abs"] = np.mean(np.abs(s))
    feats["waveform_length"] = np.sum(np.abs(np.diff(s)))
    feats["zero_cross"] = np.sum(np.diff(np.sign(s)) != 0)
    feats["slope_changes"] = np.sum(np.diff(np.sign(np.diff(s))) != 0)
    feats["var"] = np.var(s)
    feats["std"] = np.std(s)
    feats["min"] = np.min(s)
    feats["max"] = np.max(s)
    return feats


def window_to_vector(win1, win2):
    keys = [
        "rms", "mean_abs", "waveform_length", "zero_cross",
        "slope_changes", "var", "std", "min", "max"
    ]

    f1 = compute_features(win1)
    f2 = compute_features(win2)

    v1 = np.array([f1[k] for k in keys])
    v2 = np.array([f2[k] for k in keys])

    combined = np.concatenate([v1, v2]).reshape(1, -1)
    return combined


# -------------------------------
#  LIVE STREAM HANDLERS
# -------------------------------
class EMGStream:
    def __init__(self):
        self.buffer = []

    def handle(self, sender, data):
        try:
            val = float(data.decode("ascii"))
            self.buffer.append(val)
        except:
            pass

    def get_window(self):
        if len(self.buffer) >= WINDOW_SIZE:
            return self.buffer[-WINDOW_SIZE:]
        return None


M1 = EMGStream()
M2 = EMGStream()


# -------------------------------
#  CLASSIFIER
# -------------------------------
def classify(win1, win2):
    x = window_to_vector(win1, win2)
    x = scaler.transform(x)
    return model.predict(x)[0]


# -------------------------------
#  MAIN LOOP
# -------------------------------
async def run_live():
    print("Connecting to sensors...")

    async with BleakClient(M1_ADDR) as c1, BleakClient(M2_ADDR) as c2:
        await c1.start_notify(CHAR_UUID, M1.handle)
        await c2.start_notify(CHAR_UUID, M2.handle)

        print("Connected! Streaming EMG...\n")

        last_step = 0

        while True:
            w1 = M1.get_window()
            w2 = M2.get_window()

            if w1 and w2:
                if len(M1.buffer) - last_step >= STEP_SIZE:
                    last_step = len(M1.buffer)
                    prediction = classify(w1, w2)
                    print("Prediction:", prediction)

            await asyncio.sleep(0.01)


if __name__ == "__main__":
    try:
        asyncio.run(run_live())
    except KeyboardInterrupt:
        print("\nStopping live classifier.")
