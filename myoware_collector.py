# myoware_collector.py — BLE picker + ASCII preview + column cycling
# Keys: SPACE=start/stop save, L=set label, C=cycle plotted column, R=toggle raw preview, Q=quit

import asyncio, sys, os, csv, re, threading, collections
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from bleak import BleakScanner, BleakClient

# Windows BLE loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DATA_DIR = "emg_data"
os.makedirs(DATA_DIR, exist_ok=True)

def ts_name(prefix: str, ext="csv"):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

class Collector:
    def __init__(self):
        # BLE state
        self.loop = None
        self.client: BleakClient | None = None
        self.stop_event = None
        self.device_addr, self.device_name = "", ""
        self.char_uuid = ""

        # parsing/preview
        self.num_re = re.compile(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
        self.preview_raw = True     # show a few incoming lines in console
        self.preview_count = 30     # how many lines to print once
        self._printed = 0
        self._line_buf = {"t": ""}

        # columns (we’ll keep up to 6 numeric columns per line)
        self.max_cols = 6
        self.cols = [collections.deque(maxlen=3000) for _ in range(self.max_cols)]
        self.col_count = 0          # how many numeric columns have been seen
        self.col_idx = 0            # which column we plot (0-based)

        # recording
        self.recording = False
        self.label = None
        self.rows = []  # dicts

        # plot
        self.fig, self.ax = plt.subplots(figsize=(12, 6))
        (self.line,) = self.ax.plot([], [], linewidth=1)
        self.ax.grid(True)
        self.ax.set_xlabel("sample")
        self.ax.set_ylabel("value")
        self._set_title()

    # ---------- helpers ----------
    def _set_title(self):
        base = f"MyoWare BLE — SPACE: start/stop, L: label, C: column({self.col_idx+1}), R: raw, Q: quit"
        if self.recording:
            self.ax.set_title(f"{base}   |  REC '{self.label}' samples={len(self.rows)}")
        else:
            self.ax.set_title(base)

    async def _get_services(self, client):
        # Bleak compatibility: method vs property vs cached attribute
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

    # ---------- pickers ----------
    async def pick_device(self):
        while True:
            print("\n[SCAN] Searching for BLE devices (8s)...")
            devs = await BleakScanner.discover(timeout=8.0)
            if devs:
                print("\nFound devices:")
                for i, d in enumerate(devs, 1):
                    print(f"[{i}] {(d.name or '(no name)')} | {d.address}")
            else:
                print("No BLE devices found. Ensure the Wireless Shield is powered & advertising.")

            sel = input("\nEnter number, 'r' to rescan, or paste address: ").strip()
            if not sel: 
                continue
            if sel.lower() == "r":
                continue
            if sel[0].isdigit():
                idx = int(sel)
                if 1 <= idx <= len(devs):
                    d = devs[idx-1]
                    return d.address, (d.name or "")
                print("Invalid index.")
            else:
                return sel, ""

    async def pick_notify_char(self, client):
        svcs = await self._get_services(client)

        # Prefer Nordic UART TX first
        NUS_SVC = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
        NUS_TX  = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
        preferred = None
        for s in svcs:
            try:
                if s.uuid.lower() == NUS_SVC:
                    for ch in s.characteristics:
                        if ch.uuid.lower() == NUS_TX and "notify" in ch.properties:
                            preferred = ch.uuid
            except Exception:
                pass

        notify_list = []
        for s in svcs:
            try:
                for ch in s.characteristics:
                    if "notify" in ch.properties:
                        notify_list.append((s.uuid, ch))
            except Exception:
                pass

        if not notify_list:
            print("\n[ERROR] No NOTIFY characteristics found. Services present:")
            for s in svcs:
                try:
                    print(" SERVICE", s.uuid, getattr(s, "description", ""))
                    for ch in s.characteristics:
                        print("   -", ch.uuid, ch.properties)
                except Exception:
                    pass
            raise RuntimeError("No NOTIFY characteristic on this device.")

        if preferred:
            ordered = [(s, ch) for (s, ch) in notify_list if ch.uuid == preferred] + \
                      [(s, ch) for (s, ch) in notify_list if ch.uuid != preferred]
        else:
            ordered = notify_list

        print("\nAvailable NOTIFY characteristics:")
        for i, (s_uuid, ch) in enumerate(ordered, 1):
            print(f"[{i}] Char: {ch.uuid}  | Service: {s_uuid} | Props: {','.join(ch.properties)}")

        while True:
            sel = input("\nPick NOTIFY characteristic number: ").strip()
            if sel.isdigit():
                idx = int(sel)
                if 1 <= idx <= len(ordered):
                    return ordered[idx-1][1].uuid
            print("Invalid selection.")

    # ---------- parsing ----------
    def _handle_line(self, ln: str, hexstr: str):
        # extract up to max_cols numbers from this line
        nums = self.num_re.findall(ln)
        if not nums:
            return
        self.col_count = max(self.col_count, min(len(nums), self.max_cols))
        for i in range(min(len(nums), self.max_cols)):
            try:
                v = float(nums[i])
            except ValueError:
                continue
            self.cols[i].append(v)

        # append a row for saving (use the current plotted column)
        try:
            v_plot = float(nums[min(self.col_idx, len(nums)-1)])
        except Exception:
            v_plot = None
        if self.recording and self.label and v_plot is not None:
            self.rows.append({
                "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                "device": self.device_name,
                "address": self.device_addr,
                "char_uuid": self.char_uuid,
                "label": self.label,
                "col_index": self.col_idx+1,
                "value": v_plot,
                "payload_ascii": ln,
                "payload_hex": hexstr
            })

        # one-time preview
        if self.preview_raw and self._printed < self.preview_count:
            print(f"[RAW] {ln}")
            self._printed += 1
            if self._printed >= self.preview_count:
                print("[RAW] (preview muted — press 'R' to toggle)")

    def notify_handler(self, _sender: int, data: bytearray):
        # decode ASCII, buffer partial lines, feed complete lines to parser
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        if not text:
            return
        hexstr = data.hex()

        self._line_buf["t"] += text
        parts = re.split(r"[\r\n]+", self._line_buf["t"])
        self._line_buf["t"] = parts[-1]
        for ln in parts[:-1]:
            ln = ln.strip()
            if ln:
                self._handle_line(ln, hexstr)

        # try a clean numeric partial (rare, but handy)
        chunk = self._line_buf["t"].strip()
        if chunk and self.num_re.fullmatch(chunk):
            self._handle_line(chunk, hexstr)
            self._line_buf["t"] = ""

    # ---------- async core ----------
    async def async_task(self):
        self.device_addr, self.device_name = await self.pick_device()
        print(f"\n[INFO] Connecting to {self.device_name or '(no name)'} @ {self.device_addr} ...")
        self.client = BleakClient(self.device_addr, timeout=20.0)
        await self.client.connect()
        print("[INFO] Connected:", getattr(self.client, "is_connected", False))
        if not getattr(self.client, "is_connected", False):
            return

        self.char_uuid = await self.pick_notify_char(self.client)
        print(f"[INFO] Subscribing to: {self.char_uuid}")
        await self.client.start_notify(self.char_uuid, self.notify_handler)

        print("\n✓ Streaming. Controls in the plot window:")
        print("   SPACE: start/stop recording")
        print("   L:     change label")
        print("   C:     cycle plotted column (when multiple numbers per line)")
        print("   R:     toggle raw preview in console")
        print("   Q:     quit\n")

        self.stop_event = asyncio.Event()
        await self.stop_event.wait()

        try:
            await self.client.stop_notify(self.char_uuid)
        except Exception:
            pass
        try:
            await self.client.disconnect()
        except Exception:
            pass

    # ---------- UI ----------
    def update_plot(self, _):
        # choose the selected column to plot
        if self.col_count == 0:
            return (self.line,)
        idx = min(self.col_idx, self.col_count-1)
        y = list(self.cols[idx])
        if not y:
            return (self.line,)
        x = list(range(len(y)))
        self.line.set_data(x, y)
        self.ax.set_xlim(0, max(200, len(y)))
        ymin, ymax = min(y), max(y)
        pad = (ymax - ymin) * 0.15 if ymax > ymin else 1.0
        self.ax.set_ylim(ymin - pad, ymax + pad)
        self._set_title()
        return (self.line,)

    def on_key(self, ev):
        k = (ev.key or "").lower()
        if k == " ":
            if not self.recording:
                lab = input("\nEnter gesture label: ").strip()
                if lab:
                    self.label = lab
                    self.rows.clear()
                    self.recording = True
                    print(f"🔴 Recording '{lab}'...")
            else:
                self.recording = False
                self.save_csv()
        elif k == "l":
            lab = input("\nEnter new label: ").strip()
            if lab:
                self.label = lab
                print(f"Label set to '{lab}'.")
        elif k == "c":
            if self.col_count > 0:
                self.col_idx = (self.col_idx + 1) % max(1, self.col_count)
                print(f"[INFO] Plotting column {self.col_idx+1}/{self.col_count}")
        elif k == "r":
            self.preview_raw = not self.preview_raw
            self._printed = 0
            print(f"[INFO] Raw preview: {'ON' if self.preview_raw else 'OFF'}")
        elif k == "q":
            if self.loop and self.stop_event:
                self.loop.call_soon_threadsafe(self.stop_event.set)
            plt.close()

    def save_csv(self):
        if not self.rows:
            print("No data to save.")
            return
        base = (self.device_name + "_" if self.device_name else "") + (self.label or "session")
        fname = os.path.join(DATA_DIR, ts_name(base))
        with open(fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "timestamp","device","address","char_uuid","label","col_index","value","payload_ascii","payload_hex"
            ])
            w.writeheader(); w.writerows(self.rows)
        print(f"💾 Saved {len(self.rows)} samples → {fname}")

    # ---------- orchestration ----------
    def run(self):
        def bg():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self.async_task())
            finally:
                if self.loop.is_running():
                    self.loop.stop()
                self.loop.close()

        t = threading.Thread(target=bg, daemon=True)
        t.start()

        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        ani = FuncAnimation(self.fig, self.update_plot, interval=50, blit=True, cache_frame_data=False)
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
    print("MyoWare 2.0 Collector — pick device & NOTIFY char, preview ASCII, choose column")
    print("Do NOT pair in Windows Settings. Let this app connect directly.")
    Collector().run()

if __name__ == "__main__":
    main()
