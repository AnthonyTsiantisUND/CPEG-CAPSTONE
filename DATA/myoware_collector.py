# myoware_collector.py — Auto-connect, fixed labels, sequential CSV,
#                        session-only plot + PNG snapshot (Agg), plot resets each recording
# Keys:
#   [1] flat hand   [2] closing fist   [3] opening fist
#   SPACE = start/stop recording (uses selected label)
#   C = cycle plotted column
#   Q = quit

import asyncio, sys, os, csv, re, threading, time
from datetime import datetime
import matplotlib
# Keep interactive TkAgg for the live window (default on Windows).
# IMPORTANT: We will use an Agg-only, Tk-free Figure for PNG snapshots.
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from bleak import BleakScanner, BleakClient
from typing import List
from threading import Lock

# ---------- Preferred device (auto-connect) ----------
PREFERRED_ADDR = "88:13:BF:14:F7:1E"
PREFERRED_NAME = "MyoWareSensor1"

# ---------- Fixed motion labels ----------
LABELS = {
    "1": ("flat hand",   "flat_hand"),
    "2": ("closing fist","closing_fist"),
    "3": ("opening fist","opening_fist"),
}

# Windows BLE loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DATA_DIR = "emg_data"
os.makedirs(DATA_DIR, exist_ok=True)

def next_sequential_filename(label_slug: str, ext: str = "csv") -> str:
    """Return '<label_slug>_<n>.<ext>' where n is the next unused integer in DATA_DIR."""
    pattern = re.compile(rf"^{re.escape(label_slug)}_(\d+)\.{re.escape(ext)}$", re.IGNORECASE)
    max_n = 0
    for name in os.listdir(DATA_DIR):
        m = pattern.match(name)
        if m:
            try:
                max_n = max(max_n, int(m.group(1)))
            except ValueError:
                pass
    return f"{label_slug}_{max_n + 1}.{ext}"

class Collector:
    def __init__(self):
        # BLE state
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client: BleakClient | None = None
        self.stop_event: asyncio.Event | None = None
        self.device_addr, self.device_name = "", ""
        self.char_uuid = ""

        # parsing (numeric extraction)
        self.num_re = re.compile(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
        self._line_buf = {"t": ""}

        # thread safety for shared buffers (BLE thread <-> UI thread)
        self.lock = Lock()

        # columns (store up to 6 numeric columns; grow forever)
        self.max_cols = 6
        self.cols: List[List[float]] = [[] for _ in range(self.max_cols)]
        self.col_count = 0
        self.col_idx = 0

        # recording/session
        self.recording = False
        self.label_human = None  # e.g., "closing fist"
        self.label_slug  = None  # e.g., "closing_fist"
        self.rows = []           # dicts to be written to CSV (session-only)
        self.session_start_idx = [0 for _ in range(self.max_cols)]  # where current session starts in each column
        self.session_started_at = None  # timestamp when SPACE pressed

        # plot (interactive Tk window on main thread)
        self.fig, self.ax = plt.subplots(figsize=(12, 6))
        (self.line,) = self.ax.plot([], [], linewidth=1.25)
        self.ax.grid(True)
        self.ax.set_xlabel("sample (current session)")
        self.ax.set_ylabel("value")
        # expand-only axes (per session)
        self._xmax = 200
        self.ax.set_xlim(0, self._xmax)
        self._ymin = None
        self._ymax = None
        self._set_title()

        # keep a reference to the animation (prevents GC)
        self.ani = FuncAnimation(self.fig, self.update_plot, interval=50, blit=False, cache_frame_data=False)

        # connect keys
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)

    # ---------- UI helpers ----------
    def _label_status(self):
        if self.label_human:
            return f"label: {self.label_human}"
        return "label: (press 1/2/3)"

    def _set_title(self):
        base = f"[1] flat hand   [2] closing fist   [3] opening fist   |   C: column({self.col_idx+1})   |   Q: quit"
        status = self._label_status()
        if self.recording:
            self.ax.set_title(f"MyoWare BLE — {base}    |   REC '{self.label_human}' samples={len(self.rows)}")
        else:
            self.ax.set_title(f"MyoWare BLE — {base}    |   {status}")

    # ---------- BLE service helpers ----------
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

    async def pick_notify_char_auto(self, client):
        svcs = await self._get_services(client)

        # Prefer Nordic UART TX (notify)
        NUS_SVC = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
        NUS_TX  = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

        # 1) Try the exact preferred UUID first
        for s in svcs:
            try:
                if s.uuid.lower() == NUS_SVC:
                    for ch in s.characteristics:
                        if ch.uuid.lower() == NUS_TX and "notify" in ch.properties:
                            return ch.uuid
            except Exception:
                pass

        # 2) Otherwise, first NOTIFY we can find
        for s in svcs:
            try:
                for ch in s.characteristics:
                    if "notify" in ch.properties:
                        return ch.uuid
            except Exception:
                pass

        # 3) Nothing found → raise with a useful dump
        print("\n[ERROR] No NOTIFY characteristics found. Services present:")
        for s in svcs:
            try:
                print(" SERVICE", s.uuid, getattr(s, "description", ""))
                for ch in s.characteristics:
                    print("   -", ch.uuid, ch.properties)
            except Exception:
                pass
        raise RuntimeError("No NOTIFY characteristic on this device.")

    # ---------- parsing ----------
    def _handle_line(self, ln: str, hexstr: str):
        nums = self.num_re.findall(ln)
        if not nums:
            return

        with self.lock:
            self.col_count = max(self.col_count, min(len(nums), self.max_cols))
            for i in range(min(len(nums), self.max_cols)):
                try:
                    v = float(nums[i])
                    self.cols[i].append(v)  # grow forever
                except ValueError:
                    continue

            # append a row for saving (use the current plotted column)
            try:
                v_plot = float(nums[min(self.col_idx, len(nums)-1)])
            except Exception:
                v_plot = None
            if self.recording and self.label_slug and v_plot is not None:
                self.rows.append({
                    "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                    "device": self.device_name,
                    "address": self.device_addr,
                    "char_uuid": self.char_uuid,
                    "label": self.label_slug,
                    "col_index": self.col_idx+1,
                    "value": v_plot,
                    "payload_ascii": ln,
                    "payload_hex": hexstr
                })

    def notify_handler(self, _sender: int, data: bytearray):
        # decode ASCII, buffer partial lines, feed complete lines to parser
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        if not text:
            return
        hexstr = data.hex()

        # We only mutate the buffer locally; then pass complete lines to _handle_line (which locks).
        self._line_buf["t"] += text
        parts = re.split(r"[\r\n]+", self._line_buf["t"])
        self._line_buf["t"] = parts[-1]
        for ln in parts[:-1]:
            ln = ln.strip()
            if ln:
                self._handle_line(ln, hexstr)

        # If the buffer currently holds a standalone number, consume it.
        chunk = self._line_buf["t"].strip()
        if chunk and self.num_re.fullmatch(chunk):
            self._handle_line(chunk, hexstr)
            self._line_buf["t"] = ""

    # ---------- connection logic (no prompts) ----------
    async def connect_auto(self):
        """
        1) Try direct connect to PREFERRED_ADDR.
        2) If it fails, scan up to ~10s and auto-pick a device whose name or address matches.
        3) If not found, raise a clear error (no interactive input).
        """
        # 1) Direct connect
        try:
            print(f"\n[INFO] Connecting (preferred) {PREFERRED_NAME or '(no name)'} @ {PREFERRED_ADDR} ...")
            client = BleakClient(PREFERRED_ADDR, timeout=20.0)
            await client.connect()
            if getattr(client, "is_connected", False):
                self.client = client
                self.device_addr = PREFERRED_ADDR
                self.device_name = PREFERRED_NAME
                print("✅ Connected via preferred address.")
                return
        except Exception as e:
            print(f"[WARN] Preferred connect failed: {e}")

        # 2) Scan and auto-pick
        print("[INFO] Scanning for matching device (up to ~10s)...")
        found = None
        t0 = time.time()
        while time.time() - t0 < 10.0 and not found:
            try:
                devs = await BleakScanner.discover(timeout=2.0)
            except Exception as e:
                print(f"[WARN] Scan hiccup: {e}")
                devs = []
            for d in devs:
                name = (d.name or "").strip()
                addr = (d.address or "").strip()
                if addr.upper() == PREFERRED_ADDR.upper() or name == PREFERRED_NAME:
                    found = d
                    break

        if not found:
            raise RuntimeError("Could not find preferred device by name or address during scan.")

        print(f"[INFO] Connecting (scanned) {(found.name or '(no name)')} @ {found.address} ...")
        client = BleakClient(found.address, timeout=20.0)
        await client.connect()
        if not getattr(client, "is_connected", False):
            raise RuntimeError("Device appeared, but connection failed.")
        self.client = client
        self.device_addr = found.address
        self.device_name = found.name or ""
        print("✅ Connected via scan match.")

    # ---------- async core ----------
    async def async_task(self):
        await self.connect_auto()

        # Auto-pick NOTIFY characteristic (prefer Nordic UART TX)
        self.char_uuid = await self.pick_notify_char_auto(self.client)
        print(f"[INFO] Subscribing to: {self.char_uuid}")
        await self.client.start_notify(self.char_uuid, self.notify_handler)

        print("\n✓ Streaming. Controls:")
        print("   [1] flat hand   [2] closing fist   [3] opening fist")
        print("   SPACE: start/stop recording (uses currently selected motion)")
        print("   C:     cycle plotted column (when multiple numbers per line)")
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

    # ---------- plotting & keyboard ----------
    def update_plot(self, _):
        # Show ONLY the current session segment (from session_start_idx to end)
        with self.lock:
            if self.col_count == 0:
                return (self.line,)
            idx = min(self.col_idx, self.col_count-1)
            y_all = self.cols[idx]
            if not y_all:
                return (self.line,)

            start = self.session_start_idx[idx]
            if start < 0 or start > len(y_all):
                start = len(y_all)  # safety

            y = y_all[start:]  # session-only view
            n = len(y)
            x = range(n)
            self.line.set_data(x, y)

            # X axis: expand right edge as needed (per session)
            if n > self._xmax:
                self._xmax = n
                self.ax.set_xlim(0, self._xmax)

            # Y axis: expand bounds as needed (never shrink during the session)
            if n > 0:
                ymin_cur, ymax_cur = min(y), max(y)
                if self._ymin is None:
                    self._ymin, self._ymax = ymin_cur, ymax_cur
                else:
                    if ymin_cur < self._ymin: self._ymin = ymin_cur
                    if ymax_cur > self._ymax: self._ymax = ymax_cur
                pad = (self._ymax - self._ymin) * 0.15 if self._ymax > self._ymin else 1.0
                self.ax.set_ylim(self._ymin - pad, self._ymax + pad)

        self._set_title()
        return (self.line,)

    def _reset_session_view(self):
        """Reset the visible plot for a fresh session (without clearing historical buffers)."""
        with self.lock:
            # mark new start for each column at current length
            for i in range(self.max_cols):
                self.session_start_idx[i] = len(self.cols[i])
            # reset axes scaling for the new session
            self._ymin = None
            self._ymax = None
            self._xmax = 200
            self.line.set_data([], [])

        self.ax.set_xlim(0, self._xmax)
        self.ax.figure.canvas.draw_idle()

    def on_key(self, ev):
        k = (ev.key or "").lower()

        # Label hotkeys
        if k in LABELS:
            human, slug = LABELS[k]
            self.label_human, self.label_slug = human, slug
            print(f"[INFO] Selected label: {human}  (slug: {slug})")
            self._set_title()
            return

        if k == " ":
            if not self.recording:
                if not self.label_slug:
                    print("Choose a label first: press 1/2/3.")
                    return
                # start recording — reset session view & rows
                self._reset_session_view()
                with self.lock:
                    self.rows.clear()
                self.session_started_at = time.time()
                self.recording = True
                print(f"Recording '{self.label_human}'...")
            else:
                # stop and save (CSV + session-only PNG via Agg)
                self.recording = False
                self.save_csv_and_png()
        elif k == "c":
            with self.lock:
                if self.col_count > 0:
                    self.col_idx = (self.col_idx + 1) % max(1, self.col_count)
                    print(f"[INFO] Plotting column {self.col_idx+1}/{self.col_count}")
        elif k == "q":
            if self.loop and self.stop_event:
                self.loop.call_soon_threadsafe(self.stop_event.set)
            plt.close()

    # ---------- save (CSV + session-only PNG via Agg) ----------
    def save_csv_and_png(self):
        with self.lock:
            if not self.rows:
                print("No data to save.")
                return
            rows_copy = list(self.rows)  # snapshot under lock
            label_human = self.label_human
            label_slug = self.label_slug

        # CSV: session-only samples already in rows_copy
        fname_csv = next_sequential_filename(label_slug, "csv")
        fpath_csv = os.path.join(DATA_DIR, fname_csv)
        with open(fpath_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "timestamp","device","address","char_uuid","label",
                "col_index","value","payload_ascii","payload_hex"
            ])
            w.writeheader(); w.writerows(rows_copy)
        print(f"Saved {len(rows_copy)} samples → {fpath_csv}")

        # PNG: build a small, Tk-free Agg figure from the session samples
        xs = list(range(len(rows_copy)))
        ys = [r["value"] for r in rows_copy if r.get("value") is not None]

        if xs and ys and len(ys) == len(xs):
            fig2 = Figure(figsize=(12, 4))
            FigureCanvas(fig2)  # tie Agg canvas
            ax2 = fig2.add_subplot(111)
            ax2.plot(xs, ys, linewidth=1.25)
            ax2.set_title(f"EMG — {label_human} (session)")
            ax2.set_xlabel("sample (session)")
            ax2.set_ylabel("value")
            ax2.grid(True, alpha=0.3)

            fname_png = os.path.splitext(fname_csv)[0] + ".png"
            fpath_png = os.path.join(DATA_DIR, fname_png)
            fig2.savefig(fpath_png, dpi=150, bbox_inches="tight")
            # No plt.close(fig2) needed; this is a pure Agg Figure not registered with pyplot.
            print(f"Saved plot snapshot → {fpath_png}")
        else:
            print("No data to plot for PNG snapshot.")

    # ---------- orchestration ----------
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
            plt.show()  # UI/main thread
        finally:
            if self.loop and self.stop_event:
                try:
                    self.loop.call_soon_threadsafe(self.stop_event.set)
                except Exception:
                    pass
            t.join(timeout=2.0)
            print("Disconnected")

def main():
    print("MyoWare 2.0 Collector — auto-connect, fixed labels, sequential CSV")
    print("Session-only plot resets on start; session-only PNG saved on stop (Agg backend, thread-safe).")
    print("Labels: [1] flat hand, [2] closing fist, [3] opening fist")
    print("Do NOT pair in Windows Settings. Let this app connect directly.")
    Collector().run()

if __name__ == "__main__":
    main()
