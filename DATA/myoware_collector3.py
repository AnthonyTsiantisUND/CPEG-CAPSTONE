import asyncio
import sys
import os
import csv
import threading
from datetime import datetime
import time

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from bleak import BleakClient
from threading import Lock

# ---------------------------------------------------------------------
# UPDATE THESE ADDRESSES
# ---------------------------------------------------------------------
SENSOR1_NAME = "MyoWareSensor1"
SENSOR1_ADDR = "88:13:BF:14:F7:1E"

SENSOR2_NAME = "MyoWareSensor2"
SENSOR2_ADDR = "88:13:BF:13:67:56"
# ---------------------------------------------------------------------

LABELS = {
    "1": ("flat hand", "flat_hand"),
    "2": ("closed fist", "closed_fist"),
}

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DATA_DIR = "emg_dual_sbs"
os.makedirs(DATA_DIR, exist_ok=True)


def next_filename(label_slug):
    i = 1
    while True:
        fn = f"{label_slug}_{i}.csv"
        if not os.path.exists(os.path.join(DATA_DIR, fn)):
            return fn
        i += 1


class DualCollector:
    def __init__(self):
        # BLE state
        self.client1 = None
        self.client2 = None
        self.char1 = None
        self.char2 = None

        self.loop = None
        self.stop_event = None

        # EMG buffers
        self.lock = Lock()
        self.data1 = []
        self.data2 = []

        # Recording state
        self.recording = False
        self.label_human = None
        self.label_slug = None
        self.rows = []

        # ------------------- PLOTTING (two subplots) -------------------
        self.fig, (self.ax1, self.ax2) = plt.subplots(1, 2, figsize=(14, 6))

        (self.line1,) = self.ax1.plot([], [], color="tab:blue", linewidth=1.25)
        (self.line2,) = self.ax2.plot([], [], color="tab:orange", linewidth=1.25)

        self.ax1.set_title("Sensor 1")
        self.ax2.set_title("Sensor 2")

        for ax in (self.ax1, self.ax2):
            ax.grid(True)
            ax.set_xlabel("sample")
            ax.set_ylabel("value (0–255)")

        self.ani = FuncAnimation(self.fig, self.update_plot, interval=50)
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)

    # ------------------------------------------------------------------
    # BLE service discovery that works on ALL Bleak versions
    # ------------------------------------------------------------------
    async def safe_get_services(self, client):
        if hasattr(client, "get_services"):
            try:
                return await client.get_services()
            except:
                pass

        if hasattr(client, "services") and client.services:
            return client.services

        if hasattr(client, "_get_services"):
            try:
                await client._get_services()      # Windows fallback
                return client.services
            except:
                pass

        raise RuntimeError("Cannot obtain BLE services on this Bleak backend.")

    # ------------------------------------------------------------------
    # NOTIFY HANDLERS
    # ------------------------------------------------------------------
    def notify1(self, _, data):
        if not data:
            return
        v = int(data[0])
        with self.lock:
            self.data1.append(v)
            if self.recording:
                self.rows.append({
                    "timestamp": datetime.now().isoformat(),
                    "sensor": SENSOR1_NAME,
                    "value": v,
                    "label": self.label_slug,
                })

    def notify2(self, _, data):
        if not data:
            return
        v = int(data[0])
        with self.lock:
            self.data2.append(v)
            if self.recording:
                self.rows.append({
                    "timestamp": datetime.now().isoformat(),
                    "sensor": SENSOR2_NAME,
                    "value": v,
                    "label": self.label_slug,
                })

    # ------------------------------------------------------------------
    # CONNECT ONE SENSOR
    # ------------------------------------------------------------------
    async def connect_sensor(self, name, addr, sensor_id):
        print(f"[INFO] Connecting to {name} @ {addr}")
        client = BleakClient(addr)

        await client.connect()
        if not client.is_connected:
            raise RuntimeError(f"Failed to connect to {name}")

        services = await self.safe_get_services(client)

        notify_uuid = None
        for s in services:
            for ch in s.characteristics:
                if "notify" in ch.properties:
                    notify_uuid = ch.uuid
                    break
            if notify_uuid:
                break

        if not notify_uuid:
            raise RuntimeError(f"{name} has no notify characteristic.")

        print(f"[INFO] {name}: NOTIFY → {notify_uuid}")

        if sensor_id == 1:
            await client.start_notify(notify_uuid, self.notify1)
            self.client1 = client
            self.char1 = notify_uuid
        else:
            await client.start_notify(notify_uuid, self.notify2)
            self.client2 = client
            self.char2 = notify_uuid

    # ------------------------------------------------------------------
    # MAIN ASYNC TASK
    # ------------------------------------------------------------------
    async def async_task(self):
        await asyncio.gather(
            self.connect_sensor(SENSOR1_NAME, SENSOR1_ADDR, 1),
            self.connect_sensor(SENSOR2_NAME, SENSOR2_ADDR, 2),
        )

        print("\n✓ BOTH sensors connected & streaming\n")
        print("Controls:")
        print("   1 = flat hand")
        print("   2 = closed fist")
        print("   SPACE = start/stop recording")
        print("   Q = quit\n")

        self.stop_event = asyncio.Event()
        await self.stop_event.wait()

        # Cleanup
        try:
            if self.client1 and self.char1:
                await self.client1.stop_notify(self.char1)
                await self.client1.disconnect()
        except:
            pass

        try:
            if self.client2 and self.char2:
                await self.client2.stop_notify(self.char2)
                await self.client2.disconnect()
        except:
            pass

    # ------------------------------------------------------------------
    # PLOTTING UPDATE (continuous)
    # ------------------------------------------------------------------
    def update_plot(self, _):
        with self.lock:
            y1 = list(self.data1)
            y2 = list(self.data2)

        x1 = list(range(len(y1)))
        x2 = list(range(len(y2)))

        # Sensor 1
        self.line1.set_data(x1, y1)
        self.ax1.set_xlim(0, max(10, len(x1)))
        self.ax1.relim()
        self.ax1.autoscale_view(scalex=False)

        # Sensor 2
        self.line2.set_data(x2, y2)
        self.ax2.set_xlim(0, max(10, len(x2)))
        self.ax2.relim()
        self.ax2.autoscale_view(scalex=False)

        return self.line1, self.line2

    # ------------------------------------------------------------------
    # KEYBOARD CONTROLS
    # ------------------------------------------------------------------
    def on_key(self, ev):
        k = (ev.key or "").lower()

        if k in LABELS:
            self.label_human, self.label_slug = LABELS[k]
            print(f"[INFO] Label selected: {self.label_human}")
            return

        if k == " ":
            if not self.recording:
                if not self.label_slug:
                    print("Pick label first (1 or 2).")
                    return
                print(f"[INFO] Recording '{self.label_human}'...")
                self.rows.clear()
                self.recording = True
            else:
                self.recording = False
                self.save_session()
            return

        if k == "q":
            if self.stop_event:
                self.loop.call_soon_threadsafe(self.stop_event.set)
            plt.close()
            return

    # ------------------------------------------------------------------
    # SAVE SESSION
    # ------------------------------------------------------------------
    def save_session(self):
        if not self.rows:
            print("No data to save.")
            return

        label_slug = self.label_slug
        fn = next_filename(label_slug)
        path = os.path.join(DATA_DIR, fn)

        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f, fieldnames=["timestamp", "sensor", "value", "label"]
            )
            w.writeheader()
            w.writerows(self.rows)

        print(f"[SAVE] {len(self.rows)} samples → {path}")

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------
    def run(self):
        def thread_fn():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.async_task())

        threading.Thread(target=thread_fn, daemon=True).start()
        plt.show()

        if self.stop_event:
            try:
                self.loop.call_soon_threadsafe(self.stop_event.set)
            except:
                pass

        print("Disconnected.")


def main():
    print("Dual-Sensor MyoWare Collector — Side-by-Side Live Graphs")
    DualCollector().run()


if __name__ == "__main__":
    main()
