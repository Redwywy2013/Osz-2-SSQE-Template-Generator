import os
import json
import zipfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

SSQE_SAVE_FILE = "ssqe_path.ssqel"
RECENT_FILE_CACHE = "recent_maps.cache"

# osu!lazer color palette
C_MAG = "#E664AA"
C_CYAN = "#47CBE6"
C_BG = "#111114"
C_BG2 = "#1A1A1E"
C_PANEL = "#1C1C22"
C_WHITE = "#F5F5F7"

WINDOW_W = 900
WINDOW_H = 600

# -----------------------------------------------------------
# UTIL: DOUBLE-BACKSLASH PATHS
# -----------------------------------------------------------
def double_slash_path(path):
    return path.replace("\\", "\\\\")


# -----------------------------------------------------------
# CUSTOM NEON CANVAS BUTTON
# -----------------------------------------------------------
class NeonButton:
    def __init__(self, canvas, x, y, w, h, text, command,
                 base_color=C_MAG, hover_color=C_CYAN):
        self.canvas = canvas
        self.x, self.y, self.w, self.h = x, y, w, h
        self.text = text
        self.command = command
        self.base_color = base_color
        self.hover_color = hover_color

        self.radius = 8
        self.hover = False
        self.pulse = 0

        self.tag = f"btn_{id(self)}"
        self.draw()

        canvas.tag_bind(self.tag, "<Enter>", self.on_enter)
        canvas.tag_bind(self.tag, "<Leave>", self.on_leave)
        canvas.tag_bind(self.tag, "<Button-1>", self.on_click)

    def draw(self):
        self.canvas.delete(self.tag)

        glow_color = self.hover_color if self.hover else self.base_color

        # glow behind button
        self.canvas.create_oval(
            self.x - 6, self.y - 6,
            self.x + self.w + 6, self.y + self.h + 6,
            fill=glow_color, outline="", tags=self.tag, stipple="gray50"
        )

        # main rounded shape
        self._rounded_rect(
            self.x, self.y, self.x + self.w, self.y + self.h,
            r=self.radius, fill=C_PANEL,
            outline=glow_color, width=2,
            tags=self.tag
        )

        # text
        self.canvas.create_text(
            self.x + self.w/2, self.y + self.h/2,
            text=self.text, fill=C_WHITE,
            font=("Segoe UI", 13, "bold"),
            tags=self.tag
        )

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        points = [
            x1+r, y1,
            x2-r, y1,
            x2, y1,
            x2, y1+r,
            x2, y2-r,
            x2, y2,
            x2-r, y2,
            x1+r, y2,
            x1, y2,
            x1, y2-r,
            x1, y1+r,
            x1, y1
        ]
        return self.canvas.create_polygon(points, smooth=True, **kw)

    def on_enter(self, e):
        self.hover = True
        self.draw()

    def on_leave(self, e):
        self.hover = False
        self.draw()

    def on_click(self, e):
        if self.command:
            self.command()


# -----------------------------------------------------------
# NEON LOADING SPINNER (Canvas)
# -----------------------------------------------------------
class NeonSpinner:
    def __init__(self, canvas, x, y, radius):
        self.canvas = canvas
        self.x, self.y = x, y
        self.radius = radius
        self.angle = 0
        self.running = False
        self.tag = "spinner"

    def start(self):
        self.running = True
        self._animate()

    def stop(self):
        self.running = False
        self.canvas.delete(self.tag)

    def _animate(self):
        if not self.running:
            return

        self.canvas.delete(self.tag)
        self.angle += 10

        # rotating neon arc
        start = self.angle
        extent = 270

        self.canvas.create_arc(
            self.x - self.radius, self.y - self.radius,
            self.x + self.radius, self.y + self.radius,
            start=start, extent=extent,
            outline=C_CYAN, width=4,
            style="arc", tags=self.tag
        )

        self.canvas.after(16, self._animate)


# -----------------------------------------------------------
# PROGRESS BAR
# -----------------------------------------------------------
class NeonProgressBar:
    def __init__(self, canvas, x, y, w, h):
        self.canvas = canvas
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.value = 0
        self.tag = "progressbar"
        self.draw()

    def set(self, pct):
        self.value = max(0, min(1, pct))
        self.draw()

    def draw(self):
        self.canvas.delete(self.tag)

        # background bar
        self.canvas.create_rectangle(
            self.x, self.y,
            self.x + self.w, self.y + self.h,
            fill=C_BG2, outline=C_MAG, width=2, tags=self.tag
        )

        # foreground
        fill_w = self.w * self.value
        self.canvas.create_rectangle(
            self.x, self.y,
            self.x + fill_w, self.y + self.h,
            fill=C_CYAN, outline="", tags=self.tag
        )
# -----------------------------------------------------------
# OSZ PARSING HELPERS
# -----------------------------------------------------------
def read_file_from_zip(z, filename):
    return z.read(filename).decode("utf-8", errors="ignore").splitlines()


def extract_section(lines, name):
    inside = False
    out = []
    for line in lines:
        if line.strip() == f"[{name}]":
            inside = True
            continue
        if inside:
            if line.startswith("[") and line.endswith("]"):
                break
            if line.strip():
                out.append(line.strip())
    return out


def extract_metadata(lines):
    title, artist = "", ""
    for line in lines:
        if line.startswith("Title:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("Artist:"):
            artist = line.split(":", 1)[1].strip()
    return title, artist


def extract_preview_time(lines):
    for line in lines:
        if line.startswith("PreviewTime:"):
            try:
                return int(line.split(":", 1)[1])
            except:
                return 0
    return 0


def extract_first_timing(tp_lines):
    if not tp_lines:
        return None

    parts = tp_lines[0].split(",")
    if len(parts) < 2:
        return None

    time_ms = int(float(parts[0]))
    beat_length = float(parts[1])

    bpm = 0 if beat_length == 0 else (1 / beat_length) * 1000 * 60
    return [int(round(bpm)), time_ms]


def default_json():
    return {
        "timings": [], "bookmarks": [], "vfxObjects": [], "specialObjects": [], "noteData": [],
        "currentTime": 0, "beatDivisor": 1, "exportOffset": 0,
        "mappers": "", "songName": "", "difficulty": "",
        "useCover": True, "cover": "", "customDifficulty": "",
        "songOffset": 0, "songTitle": "", "songArtist": "",
        "mapCreator": "", "mapCreatorPersonalLink": "",
        "previewStartTime": 0, "previewDuration": 20,
        "novaCover": "", "novaIcon": "", "rating": 0,
        "useVideo": False, "video": ""
    }
# ===========================================================
# MAIN APP — FULL osu!lazer UI MODE
# ===========================================================
class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SSQE OSZ Converter — osu!lazer Edition")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.root.configure(bg=C_BG)

        self.ssqe_folder = self.load_ssqe()
        self.recent = self.load_recent()

        self.canvas = tk.Canvas(self.root, bg=C_BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.spinner = NeonSpinner(self.canvas, WINDOW_W//2, WINDOW_H//2 - 40, 40)
        self.progress = NeonProgressBar(self.canvas, 50, WINDOW_H - 50, WINDOW_W - 100, 16)

        # Draw UI
        self.draw_ui()

        # Full-window drag-and-drop
        self.root.update()
        self.enable_file_drop()

    # ------------------------------------------------------
    # Windows-native file drag-and-drop (Explorer → Tkinter)
    # ------------------------------------------------------
    def enable_file_drop(self):
        try:
            import ctypes

            # Allow drop
            ctypes.windll.shell32.DragAcceptFiles(self.root.winfo_id(), True)

            # Hook window proc
            GWL_WNDPROC = -4
            WM_DROPFILES = 0x233

            DefWindowProc = ctypes.windll.user32.DefWindowProcW

            self.old_proc = ctypes.windll.user32.SetWindowLongW(
                self.root.winfo_id(),
                GWL_WNDPROC,
                self._drop_wndproc
            )
        except Exception as e:
            print("Drag-and-drop setup failed:", e)

    def _drop_wndproc(self, hwnd, msg, wParam, lParam):
        import ctypes

        WM_DROPFILES = 0x233

        if msg == WM_DROPFILES:
            self._handle_drop_files(wParam)
            return 0

        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    def _handle_drop_files(self, hDrop):
        import ctypes

        DragQueryFile = ctypes.windll.shell32.DragQueryFileW
        DragFinish = ctypes.windll.shell32.DragFinish

        # number of files dropped
        count = DragQueryFile(hDrop, 0xFFFFFFFF, None, 0)

        paths = []
        for i in range(count):
            length = DragQueryFile(hDrop, i, None, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            DragQueryFile(hDrop, i, buffer, length + 1)
            paths.append(buffer.value)

        DragFinish(hDrop)

        # filter to only .osz
        osz_files = [p for p in paths if p.lower().endswith(".osz")]
        for f in osz_files:
            self.convert_file(f)


    # ------------------------------------------------------
    # Load / Save SSQE
    # ------------------------------------------------------
    def load_ssqe(self):
        if os.path.exists(SSQE_SAVE_FILE):
            path = open(SSQE_SAVE_FILE).read().strip()
            if os.path.isdir(path):
                return path
        return None

    def save_ssqe(self, path):
        open(SSQE_SAVE_FILE, "w").write(path)
        self.ssqe_folder = path

    # ------------------------------------------------------
    # Recent files
    # ------------------------------------------------------
    def load_recent(self):
        if not os.path.exists(RECENT_FILE_CACHE):
            return []
        try:
            return json.loads(open(RECENT_FILE_CACHE).read())
        except:
            return []

    def save_recent(self):
        open(RECENT_FILE_CACHE, "w").write(json.dumps(self.recent[-10:], indent=2))

    # ------------------------------------------------------
    # UI LAYOUT
    # ------------------------------------------------------
    def draw_ui(self):
        self.canvas.delete("all")

        # Title
        self.canvas.create_text(
            WINDOW_W//2, 40,
            text="SSQE OSZ Converter",
            fill=C_WHITE,
            font=("Segoe UI Black", 28)
        )

        # SSQE label
        ssqe_text = self.ssqe_folder or "No SSQE folder selected"
        self.canvas.create_text(
            WINDOW_W//2, 85,
            text=f"SSQE Folder: {ssqe_text}",
            fill=C_MAG,
            font=("Segoe UI", 12),
            tags="ssqe_label"
        )

        # Buttons
        self.btn_ssqe = NeonButton(
            self.canvas, 50, 110, 200, 40,
            "Choose SSQE Folder", self.pick_ssqe
        )
        self.btn_pick_osz = NeonButton(
            self.canvas, WINDOW_W-250, 110, 200, 40,
            "Pick OSZ File", self.pick_osz
        )
        self.btn_batch = NeonButton(
            self.canvas, 50, 170, 200, 40,
            "Batch Convert Folder", self.pick_folder
        )

        # Recent maps title
        self.canvas.create_text(
            WINDOW_W//2, 150,
            text="Recent Maps",
            fill=C_CYAN,
            font=("Segoe UI", 14)
        )

        # Recent file listing
        self.draw_recent_list()

        # Drop zone hint
        self.canvas.create_text(
            WINDOW_W//2, WINDOW_H//2 + 120,
            text="…or drag and drop .osz files anywhere on this window…",
            fill="#6FAFCF",
            font=("Segoe UI", 11, "italic")
        )

    # ------------------------------------------------------
    # Draw recent section
    # ------------------------------------------------------
    def draw_recent_list(self):
        y = 180
        for f in self.recent[-5:][::-1]:
            base = os.path.basename(f)
            self.canvas.create_text(
                WINDOW_W//2, y,
                text=base,
                fill=C_WHITE,
                font=("Segoe UI", 11),
                tags=f"recent_{y}"
            )
            y += 22

    # ------------------------------------------------------
    # File pickers
    # ------------------------------------------------------
    def pick_ssqe(self):
        f = filedialog.askdirectory(title="Select SSQE folder")
        if f:
            self.save_ssqe(f)
            self.draw_ui()

    def pick_osz(self):
        f = filedialog.askopenfilename(
            title="Select OSZ file",
            filetypes=[("OSZ Beatmap Archive", "*.osz")]
        )
        if f:
            self.convert_file(f)

    def pick_folder(self):
        f = filedialog.askdirectory(title="Select folder containing OSZ files")
        if f:
            all_maps = [
                os.path.join(f, x) for x in os.listdir(f)
                if x.lower().endswith(".osz")
            ]
            if not all_maps:
                messagebox.showinfo("No files", "No .osz files found.")
                return
            self.convert_batch(all_maps)

    # ------------------------------------------------------
    # Drag and drop handler
    # ------------------------------------------------------
    def on_drop(self, event):
        # Windows gives weird braces sometimes
        raw = event.data.replace("{", "").replace("}", "")
        paths = raw.split()
        osz_files = [p for p in paths if p.lower().endswith(".osz")]
        for f in osz_files:
            self.convert_file(f)

    # ------------------------------------------------------
    # Conversion tasks
    # ------------------------------------------------------
    def convert_file(self, path):
        if not self.ssqe_folder:
            messagebox.showwarning("SSQE Missing", "Select SSQE folder first!")
            return

        self.spinner.start()
        t = threading.Thread(target=self._convert_thread, args=(path,))
        t.start()

    def convert_batch(self, files):
        if not self.ssqe_folder:
            messagebox.showwarning("SSQE Missing", "Select SSQE folder first!")
            return

        self.spinner.start()
        t = threading.Thread(target=self._batch_thread, args=(files,))
        t.start()

    # ------------------------------------------------------
    # Worker threads
    # ------------------------------------------------------
    def _convert_thread(self, path):
        try:
            self._convert_logic(path)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.spinner.stop()
            self.draw_ui()

    def _batch_thread(self, files):
        try:
            total = len(files)
            for i, f in enumerate(files, start=1):
                self.progress.set(i / total)
                self._convert_logic(f)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.progress.set(0)
            self.spinner.stop()
            self.draw_ui()

    # ------------------------------------------------------
    # Actual convert logic
    # ------------------------------------------------------
    def _convert_logic(self, osz_path):
        if osz_path not in self.recent:
            self.recent.append(osz_path)
            self.save_recent()

        with zipfile.ZipFile(osz_path, "r") as z:
            osu_files = [f for f in z.namelist() if f.lower().endswith(".osu")]
            if not osu_files:
                raise Exception("No .osu found in file.")

            osuf = osu_files[-1]
            lines = read_file_from_zip(z, osuf)

            title, artist = extract_metadata(lines)
            preview_time = extract_preview_time(lines)

            tp_lines = extract_section(lines, "TimingPoints")
            timing = extract_first_timing(tp_lines)

            data = default_json()
            data["songName"] = title
            data["songArtist"] = artist
            data["previewStartTime"] = preview_time
            if timing:
                data["timings"] = [timing]

            # output folder
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            folder_name = f"{artist} - {title}".strip()
            dest = os.path.join(downloads, folder_name)
            os.makedirs(dest, exist_ok=True)

            # audio
            audio = None
            for f in z.namelist():
                if f.lower().endswith(".ogg") or f.lower().endswith(".mp3"):
                    audio = f
                    break

            if audio:
                ext = os.path.splitext(audio)[1]
                out_audio = os.path.join(dest, folder_name + ext)
                with open(out_audio, "wb") as w:
                    w.write(z.read(audio))

                cached = os.path.join(self.ssqe_folder, "cached")
                os.makedirs(cached, exist_ok=True)

                out_asset = os.path.join(cached, folder_name + ".asset")
                with open(out_asset, "wb") as w:
                    w.write(z.read(audio))

            # image
            images = [f for f in z.namelist()
                      if f.lower().endswith((".jpg", ".png", ".jpeg", ".bmp"))]

            if images:
                img = images[0]
                out_img = os.path.join(dest, os.path.basename(img))
                with open(out_img, "wb") as w:
                    w.write(z.read(img))
                data["cover"] = double_slash_path(out_img)

            # write INI
            ini_path = os.path.join(dest, f"{folder_name}.ini")
            ini_text = json.dumps(data, indent=2)
            ini_text = ini_text.replace("\\\\\\\\", "\\\\")
            open(ini_path, "w").write(ini_text)

            # write txt
            txt_path = ini_path.replace(".ini", ".txt")
            open(txt_path, "w").write(f"{artist} - {title},")

    # ------------------------------------------------------
    def run(self):
        self.root.mainloop()


# ===========================================================
# RUN
# ===========================================================
if __name__ == "__main__":
    App().run()
