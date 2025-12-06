# myoware_dual_collector.py — Dual sensor support with per-packet sampling
# Keys:
#   [1] flat hand   [2] closed fist
#   SPACE = start/stop recording (uses selected label, both sensors)
#   Q = quit

import asyncio, sys, os, csv, re, threading, time
from datetime import datetime
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from bleak import BleakScanner, BleakClient
from typing import Dict
from threading import Lock

# ---------- Two sensors to connect ----------
SENSORS = [
    {"addr": "88:13:BF:14:F7:1E", "name": "MyoWareSensor1", "id": "M1"},
    {"addr": "88:13:BF:13:67:56", "name": "MyoWareSensor2", "id": "M2"},
]

# ---------- Fixed motion labels ----------
LABELS = {
    "1": ("flat hand", "flat_hand"),
    "2": ("closed fist", "closed_fist"),
    "3":("pointer finger", "pointer_finger")
}

# Folder where this script lives (should be .../CPEG-CAPSTONE/DATA)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# dual_emg *inside* the DATA folder
DATA_DIR = os.path.join(BASE_DIR, "dual_emg")
os.makedirs(DATA_DIR, exist_ok=True)


# Windows BLE loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def next_sequential_filename(label_slug: str, sensor_id: str, ext: str = "csv") -> str:
    """
    Return '<label_slug>_<sensor_id>_<n>.<ext>' where n is the next unused integer in DATA_DIR.
    Example: flat_hand_M1_1.csv
    """
    pattern = re.compile(
        rf"^{re.escape(label_slug)}_{re.escape(sensor_id)}_(\d+)\.{re.escape(ext)}$",
        re.IGNORECASE,
    )
    max_n = 0
    for name in os.listdir(DATA_DIR):
        m = pattern.match(name)
        if m:
            try:
                max_n = max(max_n, int(m.group(1)))
            except ValueError:
                pass
    return f"{label_slug}_{sensor_id}_{max_n + 1}.{ext}"


class SensorState:
    """Holds BLE + data state for a single sensor."""

    def __init__(self, info: dict):
        self.info = info  # contains addr, name, id
        self.client: BleakClient | None = None
        self.char_uuid: str = ""

        # Latest decoded EMG value and raw text/hex (updated by notify handler)
        self.latest_value: float = 0.0
        self.latest_ascii: str = ""
        self.latest_hex: str = ""

        # Sampled values used for plotting (notify handler fills this)
        self.values = []  # list[float]

        # Recorded rows for CSV
        self.rows = []  # list[dict]

        # Text parsing helpers
        self.num_re = re.compile(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
        self.line_buf: str = ""

        # Basic health info
        self.last_data_time = 0.0


class DualCollector:
    def __init__(self):
        # BLE / sensors
        self.sensors: Dict[str, SensorState] = {
            cfg["id"]: SensorState(cfg) for cfg in SENSORS
        }

        # Async loop + stop event
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop_event: asyncio.Event | None = None

        # Thread safety for shared state
        self.lock = Lock()

        # Recording/session state
        self.recording: bool = False
        self.label_human: str | None = None
        self.label_slug: str | None = None

        # Plotting setup: two subplots, one per sensor
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(12, 10))

        # Sensor ID order: first subplot = M1, second = M2 (assumes exactly 2)
        self.order = ["M1", "M2"]

        # Plot lines
        (self.line1,) = self.ax1.plot([], [], linewidth=1.25)
        (self.line2,) = self.ax2.plot([], [], linewidth=1.25)

        # Axes config
        self.ax1.grid(True)
        self.ax2.grid(True)
        self.ax1.set_xlabel("sample (current session)")
        self.ax1.set_ylabel("value")
        self.ax2.set_xlabel("sample (current session)")
        self.ax2.set_ylabel("value")

        s1_info = self.sensors[self.order[0]].info
        s2_info = self.sensors[self.order[1]].info
        self.ax1.set_title(f"Sensor {s1_info['id']} - {s1_info['name']}")
        self.ax2.set_title(f"Sensor {s2_info['id']} - {s2_info['name']}")

        self._xmax1 = 200
        self._xmax2 = 200
        self._ymin1 = None
        self._ymax1 = None
        self._ymin2 = None
        self._ymax2 = None
        self.ax1.set_xlim(0, self._xmax1)
        self.ax2.set_xlim(0, self._xmax2)

        self._set_title()

        self.ani = FuncAnimation(
            self.fig,
            self.update_plot,
            interval=50,
            blit=False,
            cache_frame_data=False,
        )
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)

    # ---------- UI helpers ----------

    def _label_status(self) -> str:
        if self.label_human:
            return f"label: {self.label_human}"
        return "label: (press 1/2)"

    def _set_title(self):
        base = "[1] flat hand   [2] closed fist  [3] pointer finger  |   Q: quit"
        status = self._label_status()
        if self.recording:
            total = sum(len(s.rows) for s in self.sensors.values())
            self.fig.suptitle(
                f"MyoWare Dual BLE — {base}    |   REC '{self.label_human}' total_samples={total}"
            )
        else:
            self.fig.suptitle(f"MyoWare Dual BLE — {base}    |   {status}")

    # ---------- BLE helpers ----------

    async def _get_services(self, client):
        if hasattr(client, "get_services"):
            try:
                gs = client.get_services
                if callable(gs):
                    try:
                        return await client.get_services()
                    except TypeError:
                        return client.get_services()
                else:
                    return gs
            except Exception:
                pass
        return getattr(client, "services", [])

    async def pick_notify_char_auto(self, client):
        svcs = await self._get_services(client)
        NUS_SVC = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
        NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

        for s in svcs:
            try:
                if s.uuid.lower() == NUS_SVC:
                    for ch in s.characteristics:
                        if ch.uuid.lower() == NUS_TX and "notify" in ch.properties:
                            return ch.uuid
            except Exception:
                pass

        for s in svcs:
            try:
                for ch in s.characteristics:
                    if "notify" in ch.properties:
                        return ch.uuid
            except Exception:
                pass

        raise RuntimeError("No NOTIFY characteristic found.")

    async def connect_sensor(self, sensor_id: str):
        st = self.sensors[sensor_id]
        addr = st.info["addr"]
        name = st.info["name"]

        # Preferred address
        try:
            print(f"\n[INFO] ({sensor_id}) Connecting preferred {name} @ {addr} ...")
            client = BleakClient(addr, timeout=20.0)
            await client.connect()
            if getattr(client, "is_connected", False):
                st.client = client
                print(f" ({sensor_id}) Connected via preferred address.")
                return
        except Exception as e:
            print(f"[WARN] ({sensor_id}) Preferred connect failed: {e}")

        # Scan fallback
        print(f"[INFO] ({sensor_id}) Scanning for matching device...")
        found = None
        t0 = time.time()
        while time.time() - t0 < 10.0 and not found:
            try:
                devs = await BleakScanner.discover(timeout=2.0)
            except Exception as e:
                print(f"[WARN] ({sensor_id}) Scan hiccup: {e}")
                devs = []
            for d in devs:
                d_name = (d.name or "").strip()
                d_addr = (d.address or "").strip()
                if d_addr.upper() == addr.upper() or d_name == name:
                    found = d
                    break
        if not found:
            raise RuntimeError(f"({sensor_id}) Device not found.")
        print(f"[INFO] ({sensor_id}) Connecting via scan @ {found.address} ...")
        client = BleakClient(found.address, timeout=20.0)
        await client.connect()
        if not getattr(client, "is_connected", False):
            raise RuntimeError(f"({sensor_id}) Device appeared, but connection failed.")
        st.client = client
        print(f" ({sensor_id}) Connected via scan match.")

    def make_notify_handler(self, sensor_id: str):
        st = self.sensors[sensor_id]

        def handler(_sender: int, data: bytearray):
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
            if not text:
                return
            hexstr = data.hex()

            st.line_buf += text
            parts = re.split(r"[\r\n]+", st.line_buf)
            st.line_buf = parts[-1]

            # Process complete lines
            for ln in parts[:-1]:
                ln = ln.strip()
                if not ln:
                    continue
                nums = st.num_re.findall(ln)
                if not nums:
                    continue
                try:
                    v = float(nums[0])  # first numeric token
                except ValueError:
                    continue

                ts = datetime.now().isoformat(timespec="milliseconds")
                with self.lock:
                    st.latest_value = v
                    st.latest_ascii = ln
                    st.latest_hex = hexstr
                    st.last_data_time = time.time()
                    # plotting buffer
                    st.values.append(v)
                    # recording buffer
                    if self.recording and self.label_slug:
                        st.rows.append({
                            "timestamp": ts,
                            "device": st.info["name"],
                            "address": st.info["addr"],
                            "char_uuid": st.char_uuid,
                            "label": self.label_slug,
                            "col_index": 1,
                            "value": v,
                            "payload_ascii": ln,
                            "payload_hex": hexstr,
                        })

            # Handle a single numeric still in buffer
            chunk = st.line_buf.strip()
            if chunk and st.num_re.fullmatch(chunk):
                try:
                    v = float(chunk)
                except ValueError:
                    return
                ts = datetime.now().isoformat(timespec="milliseconds")
                with self.lock:
                    st.latest_value = v
                    st.latest_ascii = chunk
                    st.latest_hex = hexstr
                    st.last_data_time = time.time()
                    st.values.append(v)
                    if self.recording and self.label_slug:
                        st.rows.append({
                            "timestamp": ts,
                            "device": st.info["name"],
                            "address": st.info["addr"],
                            "char_uuid": st.char_uuid,
                            "label": self.label_slug,
                            "col_index": 1,
                            "value": v,
                            "payload_ascii": chunk,
                            "payload_hex": hexstr,
                        })
                st.line_buf = ""

        return handler

    async def async_task(self):
        # Connect both sensors
        for sid in self.sensors.keys():
            await self.connect_sensor(sid)

        # Discover characteristic + subscribe
        for sid, st in self.sensors.items():
            st.char_uuid = await self.pick_notify_char_auto(st.client)
            print(f"[INFO] ({sid}) Subscribing to: {st.char_uuid}")
            await st.client.start_notify(st.char_uuid, self.make_notify_handler(sid))
            st.last_data_time = time.time()
            print(f"[INFO] ({sid}) Notify started.")

        print("\n✓ Both sensors streaming. Controls:")
        print("   [1] flat hand   [2] closed fist  [3] pointer finger")
        print("   SPACE: start/stop recording (both sensors)")
        print("   Q: quit\n")

        self.stop_event = asyncio.Event()

        # Wait until quit signal from UI
        await self.stop_event.wait()

        # Cleanup BLE
        for sid, st in self.sensors.items():
            if st.client:
                try:
                    await st.client.stop_notify(st.char_uuid)
                except Exception:
                    pass
                try:
                    await st.client.disconnect()
                except Exception:
                    pass

    # ---------- plotting & keyboard ----------

    def update_plot(self, _):
        with self.lock:
            # Sensor 1
            s1 = self.sensors[self.order[0]]
            y1 = s1.values
            if y1:
                n1 = len(y1)
                x1 = range(n1)
                self.line1.set_data(x1, y1)
                if n1 > self._xmax1:
                    self._xmax1 = n1
                    self.ax1.set_xlim(0, self._xmax1)
                ymin1, ymax1 = min(y1), max(y1)
                if self._ymin1 is None:
                    self._ymin1, self._ymax1 = ymin1, ymax1
                else:
                    if ymin1 < self._ymin1:
                        self._ymin1 = ymin1
                    if ymax1 > self._ymax1:
                        self._ymax1 = ymax1
                pad1 = (self._ymax1 - self._ymin1) * 0.15 if self._ymax1 > self._ymin1 else 1.0
                self.ax1.set_ylim(self._ymin1 - pad1, self._ymax1 + pad1)

            # Sensor 2
            s2 = self.sensors[self.order[1]]
            y2 = s2.values
            if y2:
                n2 = len(y2)
                x2 = range(n2)
                self.line2.set_data(x2, y2)
                if n2 > self._xmax2:
                    self._xmax2 = n2
                    self.ax2.set_xlim(0, self._xmax2)
                ymin2, ymax2 = min(y2), max(y2)
                if self._ymin2 is None:
                    self._ymin2, self._ymax2 = ymin2, ymax2
                else:
                    if ymin2 < self._ymin2:
                        self._ymin2 = ymin2
                    if ymax2 > self._ymax2:
                        self._ymax2 = ymax2
                pad2 = (self._ymax2 - self._ymin2) * 0.15 if self._ymax2 > self._ymin2 else 1.0
                self.ax2.set_ylim(self._ymin2 - pad2, self._ymax2 + pad2)

        self._set_title()
        return (self.line1, self.line2)

    def _reset_session_view(self):
        with self.lock:
            for st in self.sensors.values():
                st.values.clear()
                st.rows.clear()
            self._xmax1 = 200
            self._xmax2 = 200
            self._ymin1 = self._ymax1 = None
            self._ymin2 = self._ymax2 = None
            self.line1.set_data([], [])
            self.line2.set_data([], [])
            self.ax1.set_xlim(0, self._xmax1)
            self.ax2.set_xlim(0, self._xmax2)
        self.fig.canvas.draw_idle()

    def on_key(self, ev):
        k = (ev.key or "").lower()
        if k in LABELS:
            human, slug = LABELS[k]
            self.label_human, self.label_slug = human, slug
            print(f"[INFO] Selected label: {human} (slug: {slug})")
            self._set_title()
            return
        if k == " ":
            if not self.recording:
                if not self.label_slug:
                    print("Choose a label first: press 1,2, or 3.")
                    return
                self._reset_session_view()
                self.recording = True
                print(f"Recording '{self.label_human}' for BOTH sensors...")
            else:
                self.recording = False
                self.save_all_csv_and_png()
        elif k == "q":
            if self.loop and self.stop_event:
                self.loop.call_soon_threadsafe(self.stop_event.set)
            plt.close()

    # ---------- saving ----------

    def save_all_csv_and_png(self):
        """Save CSV and PNG for each sensor."""
        with self.lock:
            label_slug = self.label_slug
            label_human = self.label_human
            # Copy out state to avoid race during file IO
            snapshot = {
                sid: {
                    "rows": list(st.rows),
                    "values": list(st.values),
                    "info": st.info,
                }
                for sid, st in self.sensors.items()
            }

        if not label_slug:
            print("No label set; skipping save.")
            return

        for sid, data in snapshot.items():
            rows = data["rows"]
            vals = data["values"]
            info = data["info"]

            if not rows:
                print(f"No data to save for {sid}.")
                continue

            fname_csv = next_sequential_filename(label_slug, sid, "csv")
            fpath_csv = os.path.join(DATA_DIR, fname_csv)

            with open(fpath_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "device",
                        "address",
                        "char_uuid",
                        "label",
                        "col_index",
                        "value",
                        "payload_ascii",
                        "payload_hex",
                    ],
                )
                w.writeheader()
                w.writerows(rows)

            print(f"Saved {len(rows)} samples for {sid} → {fpath_csv}")

            # PNG snapshot
            xs = list(range(len(vals)))
            ys = vals
            if xs and ys and len(xs) == len(ys):
                fig2 = Figure(figsize=(12, 4))
                FigureCanvas(fig2)
                ax2 = fig2.add_subplot(111)
                ax2.plot(xs, ys, linewidth=1.25)
                ax2.set_title(f"EMG — {label_human} — {sid} (session)")
                ax2.set_xlabel("sample (session)")
                ax2.set_ylabel("value")
                ax2.grid(True, alpha=0.3)
                fname_png = os.path.splitext(fname_csv)[0] + ".png"
                fpath_png = os.path.join(DATA_DIR, fname_png)
                fig2.savefig(fpath_png, dpi=150, bbox_inches="tight")
                print(f"Saved plot snapshot for {sid} → {fpath_png}")
            else:
                print(f"No data to plot for PNG snapshot ({sid}).")

    # ---------- runner ----------

    def run(self):
        def bg():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self.async_task())
            finally:
                try:
                    if self.loop.is_running():
                        self.loop.stop()
                except Exception:
                    pass
                try:
                    self.loop.close()
                except Exception:
                    pass

        t = threading.Thread(target=bg, daemon=True)
        t.start()
        try:
            plt.show()
        finally:
            if self.loop and self.stop_event:
                try:
                    self.loop.call_soon_threadsafe(self.stop_event.set)
                except Exception:
                    pass
            t.join(timeout=2.0)
            print("Disconnected")


def main():
    print("MyoWare 2.0 Dual Collector — per-packet sampling (no fixed-rate sampler)")
    print("Sensors: M1 & M2 (see SENSORS list)")
    print("Labels: [1] flat hand, [2] closed fist")
    print("Data saved in 'dual_emg' (two CSVs + PNGs per session).")
    print("Do NOT pair in OS Bluetooth settings. Let this app connect directly.")
    DualCollector().run()


if __name__ == "__main__":
    main()
