"""
prtt_gui.py - Ventana del lector de diálogos (Tkinter, viene con Python en Windows).

Izquierda: archivos .rpy y sus labels (con nº de líneas de diálogo).
Centro:    las líneas de diálogo del archivo o label elegido (o resultados de la búsqueda).
Derecha:   la pose de cada personaje en escena para la línea seleccionada (sprites armados
           con las capas de las definiciones `image`), en celdas 1..N.
Abajo:     el texto completo de la línea seleccionada.
"""
import tkinter as tk
from tkinter import ttk

from dialogue import DialogueLine, build_index, count_lines, search
from sprites import HAVE_PIL, SpriteBook, build_cell_views
from stage import build_timeline

try:
    from PIL import Image, ImageTk
    HAVE_TKIMG = True
except ImportError:
    HAVE_TKIMG = False


class DialogueBrowser(tk.Tk):
    def __init__(self, db, game_dir: str):
        super().__init__()
        self.db = db
        self.index = build_index(db)
        self.book = SpriteBook(db, game_dir)
        self._timelines = {}     # label -> [Frame]
        self._photos = []        # referencias a las imágenes (Tk las borra si no se guardan)
        self.title(f"PRTT - Lector de diálogos  |  {game_dir}")
        self.geometry("1500x760")
        self.minsize(900, 520)
        self._rows = {}          # iid de la derecha -> DialogueLine
        self._groups = {}        # iid de la izquierda -> lista de DialogueLine
        self._build_ui()
        self._fill_tree()

    # ------------------------------------------------------------------ interfaz
    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        ttk.Label(top, text="Buscar:").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query, width=40)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self._on_search())
        ttk.Button(top, text="Buscar", command=self._on_search).pack(side="left")
        ttk.Button(top, text="Limpiar", command=self._clear_search).pack(side="left", padx=4)
        self.info = ttk.Label(top, text="")
        self.info.pack(side="right")

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8)

        left = ttk.Frame(panes)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select_group)
        panes.add(left, weight=1)

        right = ttk.Frame(panes)
        cols = ("n", "label", "who", "text", "where")
        self.rows = ttk.Treeview(right, columns=cols, show="headings", selectmode="browse")
        for col, title, width in (("n", "#", 45), ("label", "Label", 130), ("who", "Personaje", 110),
                                  ("text", "Texto", 520), ("where", "Archivo:línea", 150)):
            self.rows.heading(col, text=title)
            self.rows.column(col, width=width, anchor="w", stretch=(col == "text"))
        sb2 = ttk.Scrollbar(right, orient="vertical", command=self.rows.yview)
        self.rows.configure(yscrollcommand=sb2.set)
        self.rows.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")
        self.rows.bind("<<TreeviewSelect>>", self._on_select_row)
        panes.add(right, weight=4)

        side = ttk.Frame(panes, padding=(6, 0))
        self.side_title = ttk.Label(side, text="Pose en escena", font=("TkDefaultFont", 10, "bold"))
        self.side_title.pack(anchor="w", pady=(0, 4))
        self.cells_frame = ttk.Frame(side)
        self.cells_frame.pack(fill="x")
        self.side_info = tk.Text(side, height=9, wrap="word", state="disabled")
        self.side_info.pack(fill="both", expand=True, pady=(6, 0))
        panes.add(side, weight=3)

        self.detail =tk.Text(self, height=5, wrap="word", state="disabled")
        self.detail.pack(fill="x", padx=8, pady=(6, 8))

    def _fill_tree(self) -> None:
        total = count_lines(self.index)
        n_labels = sum(len(v) for v in self.index.values())
        self.info.config(text=f"{len(self.index)} archivos · {n_labels} labels · {total} líneas de diálogo")
        for file, infos in self.index.items():
            all_lines = [dl for i in infos for dl in i.lines]
            fid = self.tree.insert("", "end", text=f"{file}  ({len(all_lines)})", open=False)
            self._groups[fid] = all_lines
            for info in infos:
                lid = self.tree.insert(fid, "end", text=f"{info.name}  ({len(info.lines)})")
                self._groups[lid] = info.lines

    # ------------------------------------------------------------------ eventos
    def _show(self, lines) -> None:
        self.rows.delete(*self.rows.get_children())
        self._rows.clear()
        for w in self.cells_frame.winfo_children():
            w.destroy()
        self._set_text(self.side_info, "")
        for dl in lines:
            iid = self.rows.insert("", "end", values=(
                dl.n, dl.label, dl.speaker, dl.text.replace("\n", " ⏎ "), dl.where))
            self._rows[iid] = dl
        self._set_detail("")
        first = self.rows.get_children()
        if first:                      # selecciona la primera línea para ver su pose enseguida
            self.rows.selection_set(first[0])

    def _on_select_group(self, _event=None) -> None:
        sel = self.tree.selection()
        if sel and sel[0] in self._groups:
            self._show(self._groups[sel[0]])

    def _on_select_row(self, _event=None) -> None:
        sel = self.rows.selection()
        if sel and sel[0] in self._rows:
            dl: DialogueLine = self._rows[sel[0]]
            pose = f"   pose: {' '.join(dl.attrs)}" if dl.attrs else ""
            self._set_detail(f"{dl.speaker}{pose}   ({dl.where})\n\n{dl.text}")
            self._render_poses(dl)

    # ------------------------------------------------------------------ panel de poses
    def _frame_for(self, dl: DialogueLine):
        frames = self._timelines.get(dl.label)
        if frames is None:
            frames = self._timelines[dl.label] = build_timeline(self.db, dl.label)
        i = dl.n - 1
        if i < len(frames) and frames[i].event.file == dl.file and frames[i].event.line == dl.line:
            return frames[i]
        return next((f for f in frames if f.event.file == dl.file and f.event.line == dl.line), None)

    def _render_poses(self, dl: DialogueLine) -> None:
        for w in self.cells_frame.winfo_children():
            w.destroy()
        self._photos = []
        frame = self._frame_for(dl)
        if frame is None:
            self.side_title.config(text="Pose en escena (no disponible)")
            self._set_text(self.side_info, "")
            return
        views = build_cell_views(frame, self.db, self.book)
        stage = frame.stage
        n = max(len(views), 1)
        size = max(90, min(340, 460 // n))
        self.side_title.config(
            text=f"Fondo: {stage.bg or '-'}   ·   {len(views)} celda(s)   ·   habla: {stage.speaker or '(narrador)'}")
        infos = []
        if not HAVE_PIL:
            infos.append("Para ver los sprites instala Pillow:  py -3 -m pip install pillow")
        for col, v in enumerate(views):
            cell = ttk.Frame(self.cells_frame, padding=2)
            cell.grid(row=0, column=col, sticky="n", padx=3)
            tk.Label(cell, text=("🗣 " if v.speaking else "") + v.title, wraplength=size,
                     font=("TkDefaultFont", 9, "bold" if v.speaking else "normal")).pack()
            if v.image is not None and HAVE_TKIMG:
                res = getattr(Image, "Resampling", Image).LANCZOS
                photo = ImageTk.PhotoImage(v.image.resize((size, size), res))
                self._photos.append(photo)
                tk.Label(cell, image=photo, borderwidth=1, relief="solid").pack()
            else:
                cv = tk.Canvas(cell, width=size, height=size, highlightthickness=0)
                cv.create_rectangle(2, 2, size - 2, size - 2, dash=(4, 3))
                cv.create_text(size // 2, size // 2, text="vacía" if not v.image_name else "sin imagen")
                cv.pack()
            if v.info:
                infos.append(v.info)
        self._set_text(self.side_info, "\n\n".join(infos))

    def _set_text(self, widget, text: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.config(state="disabled")

    def _on_search(self) -> None:
        q = self.query.get()
        if not q.strip():
            return self._clear_search()
        found = search(self.index, q)
        self.tree.selection_remove(self.tree.selection())
        self._show(found)
        self.info.config(text=f"{len(found)} resultados para «{q.strip()}»")

    def _clear_search(self) -> None:
        self.query.set("")
        self.rows.delete(*self.rows.get_children())
        self._rows.clear()
        self._set_detail("")
        total = count_lines(self.index)
        n_labels = sum(len(v) for v in self.index.values())
        self.info.config(text=f"{len(self.index)} archivos · {n_labels} labels · {total} líneas de diálogo")

    def _set_detail(self, text: str) -> None:
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")


def run(db, game_dir: str) -> None:
    DialogueBrowser(db, game_dir).mainloop()
