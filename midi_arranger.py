"""
midi_arranger.py
────────────────
GUI para crear arreglos musicales MIDI usando midi_to_yaml.py y yaml_to_midi.py.

Requiere en el mismo directorio:
    midi_to_yaml.py
    yaml_to_midi.py

Dependencias:
    pip install pretty_midi mido pyyaml

Uso:
    python midi_arranger.py
"""

import sys
import os
import threading
import subprocess
import tempfile
import traceback
import importlib.util
from datetime import datetime, timezone
from copy import deepcopy

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ─────────────────────────────────────────────────────────────
# Import midi_to_yaml and yaml_to_midi from same directory
# ─────────────────────────────────────────────────────────────

def _load_module(name, filename):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(script_dir, filename)
    if not os.path.exists(path):
        messagebox.showerror(
            "Módulo faltante",
            f"No se encontró '{filename}' en:\n{script_dir}\n\n"
            f"Asegurate de que {filename} esté en la misma carpeta que midi_arranger.py"
        )
        sys.exit(1)
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

midi_to_yaml_mod = _load_module("midi_to_yaml", "midi_to_yaml.py")
yaml_to_midi_mod = _load_module("yaml_to_midi", "yaml_to_midi.py")

import yaml


# ─────────────────────────────────────────────────────────────
# GM instrument list (same as midi_to_yaml)
# ─────────────────────────────────────────────────────────────

GM_INSTRUMENTS = midi_to_yaml_mod.GM_INSTRUMENTS
GM_LIST = [f"{k} – {v}" for k, v in sorted(GM_INSTRUMENTS.items())]

TRANSFORMATIONS = [
    "transpose",
    "instrument_change",
    "velocity_scale",
    "velocity_set",
    "reverse",
    "augment",
    "diminish",
    "invert",
    "humanize",
]

TRANSFORM_PARAMS = {
    "transpose":         [("semitones", "int", 0)],
    "instrument_change": [("to_gm", "int", 0)],
    "velocity_scale":    [("factor", "float", 1.0)],
    "velocity_set":      [("value", "int", 80)],
    "reverse":           [],
    "augment":           [("duration_factor", "float", 2.0)],
    "diminish":          [("duration_factor", "float", 0.5)],
    "invert":            [("pivot_midi", "int", 60)],
    "humanize":          [("timing_ms", "float", 15.0), ("velocity_variance", "int", 8)],
}

COLORS = {
    "bg":        "#1e1e2e",
    "panel":     "#27273a",
    "card":      "#31314a",
    "accent":    "#7c6af7",
    "accent2":   "#5dcaa5",
    "danger":    "#e24b4a",
    "text":      "#e4e4f0",
    "muted":     "#888899",
    "border":    "#3f3f5a",
    "entry_bg":  "#3a3a52",
    "highlight": "#4a4a6a",
}

FONT_MONO  = ("Consolas", 10)
FONT_BODY  = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_SMALL = ("Segoe UI", 9)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def gm_number_from_str(s):
    """Extract GM number from '0 – Acoustic Grand Piano' style string."""
    try:
        return int(s.split("–")[0].strip())
    except Exception:
        return 0


def build_yaml_str(schema):
    return midi_to_yaml_mod.schema_to_yaml(schema)


# ─────────────────────────────────────────────────────────────
# TransformationRow — one transformation inside a track card
# ─────────────────────────────────────────────────────────────

class TransformationRow(tk.Frame):
    def __init__(self, parent, on_delete, initial=None, **kwargs):
        super().__init__(parent, bg=COLORS["card"], **kwargs)
        self._on_delete = on_delete
        self._param_vars = {}
        self._param_frames = {}

        top = tk.Frame(self, bg=COLORS["card"])
        top.pack(fill="x", pady=(4, 0))

        tk.Label(top, text="tipo:", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONT_SMALL).pack(side="left", padx=(0, 4))

        self._type_var = tk.StringVar(value=initial.get("type", "transpose") if initial else "transpose")
        cb = ttk.Combobox(top, textvariable=self._type_var,
                          values=TRANSFORMATIONS, state="readonly", width=18,
                          font=FONT_BODY)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._rebuild_params())

        tk.Label(top, text="razón:", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONT_SMALL).pack(side="left", padx=(10, 4))
        self._reason_var = tk.StringVar(value=initial.get("reason", "") if initial else "")
        tk.Entry(top, textvariable=self._reason_var, bg=COLORS["entry_bg"],
                 fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", font=FONT_BODY, width=22).pack(side="left")

        del_btn = tk.Button(top, text="✕", bg=COLORS["card"], fg=COLORS["danger"],
                            relief="flat", font=FONT_BOLD, cursor="hand2",
                            command=self._delete)
        del_btn.pack(side="right", padx=4)

        self._params_frame = tk.Frame(self, bg=COLORS["card"])
        self._params_frame.pack(fill="x", pady=(2, 4), padx=(16, 0))

        self._rebuild_params(initial)

        sep = tk.Frame(self, bg=COLORS["border"], height=1)
        sep.pack(fill="x", pady=(2, 0))

    def _rebuild_params(self, initial=None):
        for w in self._params_frame.winfo_children():
            w.destroy()
        self._param_vars = {}

        tf_type = self._type_var.get()
        params  = TRANSFORM_PARAMS.get(tf_type, [])

        for name, kind, default in params:
            row = tk.Frame(self._params_frame, bg=COLORS["card"])
            row.pack(side="left", padx=(0, 14))
            tk.Label(row, text=f"{name}:", bg=COLORS["card"], fg=COLORS["muted"],
                     font=FONT_SMALL).pack(side="left", padx=(0, 3))

            val = default
            if initial and name in initial:
                val = initial[name]

            if kind == "int":
                var = tk.IntVar(value=int(val))
                tk.Spinbox(row, textvariable=var, from_=-127, to=127, width=6,
                           bg=COLORS["entry_bg"], fg=COLORS["text"],
                           buttonbackground=COLORS["border"],
                           relief="flat", font=FONT_BODY).pack(side="left")
            else:
                var = tk.DoubleVar(value=float(val))
                tk.Spinbox(row, textvariable=var, from_=-10.0, to=10.0,
                           increment=0.1, format="%.2f", width=7,
                           bg=COLORS["entry_bg"], fg=COLORS["text"],
                           buttonbackground=COLORS["border"],
                           relief="flat", font=FONT_BODY).pack(side="left")

            self._param_vars[name] = (var, kind)

    def _delete(self):
        self._on_delete(self)
        self.destroy()

    def get_data(self):
        d = {"type": self._type_var.get()}
        reason = self._reason_var.get().strip()
        if reason:
            d["reason"] = reason
        for name, (var, kind) in self._param_vars.items():
            try:
                d[name] = int(var.get()) if kind == "int" else round(float(var.get()), 4)
            except Exception:
                pass
        return d


# ─────────────────────────────────────────────────────────────
# TrackCard — one track in Panel 2
# ─────────────────────────────────────────────────────────────

class TrackCard(tk.Frame):
    def __init__(self, parent, track_data, available_track_ids, on_delete, **kwargs):
        super().__init__(parent, bg=COLORS["card"],
                         highlightbackground=COLORS["border"],
                         highlightthickness=1, **kwargs)
        self._track_data = deepcopy(track_data)
        self._available_ids = available_track_ids
        self._on_delete = on_delete
        self._tf_rows = []

        self._build()

    def _build(self):
        td = self._track_data

        # ── Header ──────────────────────────────────────────
        header = tk.Frame(self, bg=COLORS["accent"], pady=4)
        header.pack(fill="x")

        id_lbl = tk.Label(header, text=f"Track {td['id']}", bg=COLORS["accent"],
                          fg="white", font=FONT_BOLD)
        id_lbl.pack(side="left", padx=8)

        self._label_var = tk.StringVar(value=td.get("label", ""))
        tk.Entry(header, textvariable=self._label_var, bg=COLORS["accent"],
                 fg="white", insertbackground="white", relief="flat",
                 font=FONT_BOLD, width=28).pack(side="left", padx=4)

        del_btn = tk.Button(header, text="Eliminar track", bg=COLORS["accent"],
                            fg="white", relief="flat", font=FONT_SMALL,
                            cursor="hand2", command=self._delete)
        del_btn.pack(side="right", padx=8)

        # ── Body ────────────────────────────────────────────
        body = tk.Frame(self, bg=COLORS["card"], padx=10, pady=6)
        body.pack(fill="x")

        # Info del track original (read-only)
        info_line = (
            f"Notas: {td.get('note_count','?')}  |  "
            f"Rango: {td.get('vocal_range',{}).get('lowest_note','?')} – "
            f"{td.get('vocal_range',{}).get('highest_note','?')}  |  "
            f"Vel: {td.get('dynamics',{}).get('velocity_min','?')}–"
            f"{td.get('dynamics',{}).get('velocity_max','?')}"
        )
        tk.Label(body, text=info_line, bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONT_SMALL).grid(row=0, column=0, columnspan=4, sticky="w")

        # source_track_id
        tk.Label(body, text="Fuente:", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONT_SMALL).grid(row=1, column=0, sticky="w", pady=(6, 2))
        src_ids = ["(mismo track)"] + [str(i) for i in self._available_ids
                                        if i != td["id"]]
        self._source_var = tk.StringVar()
        src_val = td.get("source_track_id")
        self._source_var.set(str(src_val) if src_val else "(mismo track)")
        src_cb = ttk.Combobox(body, textvariable=self._source_var,
                              values=src_ids, state="readonly", width=14,
                              font=FONT_BODY)
        src_cb.grid(row=1, column=1, sticky="w", padx=(4, 20), pady=(6, 2))

        # Instrumento
        tk.Label(body, text="Instrumento:", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONT_SMALL).grid(row=1, column=2, sticky="w", pady=(6, 2))
        current_gm = td.get("instrument", {}).get("gm_number", 0)
        current_gm_name = GM_INSTRUMENTS.get(current_gm, "Acoustic Grand Piano")
        current_str = f"{current_gm} – {current_gm_name}"
        self._instr_var = tk.StringVar(value=current_str)
        instr_cb = ttk.Combobox(body, textvariable=self._instr_var,
                                values=GM_LIST, state="readonly", width=32,
                                font=FONT_BODY)
        instr_cb.grid(row=1, column=3, sticky="w", padx=4, pady=(6, 2))

        # ── Transformaciones ────────────────────────────────
        tf_header = tk.Frame(body, bg=COLORS["card"])
        tf_header.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 2))

        tk.Label(tf_header, text="Transformaciones:", bg=COLORS["card"],
                 fg=COLORS["text"], font=FONT_BOLD).pack(side="left")

        add_btn = tk.Button(tf_header, text="+ Agregar", bg=COLORS["accent2"],
                            fg="#0a2a1e", relief="flat", font=FONT_SMALL,
                            cursor="hand2", padx=8, pady=2,
                            command=self._add_transformation)
        add_btn.pack(side="left", padx=10)

        self._tf_container = tk.Frame(body, bg=COLORS["card"])
        self._tf_container.grid(row=3, column=0, columnspan=4, sticky="ew")

        # Load existing transformations
        for tf in td.get("transformations", []):
            self._add_transformation(initial=tf)

    def _add_transformation(self, initial=None):
        row = TransformationRow(self._tf_container,
                                on_delete=lambda r: self._tf_rows.remove(r),
                                initial=initial)
        row.pack(fill="x", pady=2)
        self._tf_rows.append(row)

    def _delete(self):
        self._on_delete(self)
        self.destroy()

    def get_data(self):
        gm_str    = self._instr_var.get()
        gm_number = gm_number_from_str(gm_str)
        gm_name   = GM_INSTRUMENTS.get(gm_number, gm_str.split("–")[-1].strip())

        d = {
            "id":    self._track_data["id"],
            "label": self._label_var.get().strip(),
            "instrument": {
                "gm_number": int(gm_number),
                "gm_name":   gm_name,
            },
            "vocal_range":   self._track_data.get("vocal_range", {}),
            "dynamics":      self._track_data.get("dynamics", {}),
            "articulations": self._track_data.get("articulations", []),
            "note_count":    self._track_data.get("note_count", 0),
            "transformations": [r.get_data() for r in self._tf_rows],
        }

        src = self._source_var.get()
        if src and src != "(mismo track)":
            d["source_track_id"] = int(src)

        return d


# ─────────────────────────────────────────────────────────────
# Main application
# ─────────────────────────────────────────────────────────────

HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yaml_history")


class MidiArrangerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MIDI Arranger")
        self.geometry("1180x780")
        self.minsize(900, 600)
        self.configure(bg=COLORS["bg"])

        self._midi_path   = None
        self._schema      = None
        self._track_cards = []
        self._history     = []   # list of (timestamp_str, filepath)

        os.makedirs(HISTORY_DIR, exist_ok=True)
        self._setup_styles()
        self._build_ui()
        self._load_history_from_disk()

    # ── Styles ──────────────────────────────────────────────

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=COLORS["entry_bg"],
                        background=COLORS["entry_bg"],
                        foreground=COLORS["text"],
                        selectbackground=COLORS["accent"],
                        selectforeground="white",
                        borderwidth=0,
                        arrowcolor=COLORS["text"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLORS["entry_bg"])],
                  selectbackground=[("readonly", COLORS["accent"])])
        style.configure("Vertical.TScrollbar",
                        background=COLORS["panel"],
                        troughcolor=COLORS["bg"],
                        arrowcolor=COLORS["muted"],
                        borderwidth=0)

    # ── UI skeleton ─────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        topbar = tk.Frame(self, bg=COLORS["accent"], height=48)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Label(topbar, text="MIDI Arranger",
                 bg=COLORS["accent"], fg="white", font=FONT_TITLE,
                 padx=16).pack(side="left", fill="y")
        tk.Label(topbar,
                 text="midi_to_yaml  →  editar arreglo  →  yaml_to_midi",
                 bg=COLORS["accent"], fg="#c8c0ff", font=FONT_SMALL).pack(side="left")

        # Main area: 3 columns
        main = tk.Frame(self, bg=COLORS["bg"])
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, minsize=260, weight=0)
        main.columnconfigure(1, weight=1)
        main.columnconfigure(2, minsize=280, weight=0)
        main.rowconfigure(0, weight=1)

        self._build_panel1(main)
        self._build_panel2(main)
        self._build_panel3(main)

    # ── Panel 1: Cargar MIDI ────────────────────────────────

    def _build_panel1(self, parent):
        p = tk.Frame(parent, bg=COLORS["panel"], padx=12, pady=12)
        p.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)

        tk.Label(p, text="1 · Cargar MIDI", bg=COLORS["panel"],
                 fg=COLORS["accent"], font=FONT_TITLE).pack(anchor="w")
        tk.Frame(p, bg=COLORS["accent"], height=2).pack(fill="x", pady=(2, 10))

        # File picker
        tk.Button(p, text="Seleccionar archivo .mid",
                  bg=COLORS["accent"], fg="white", relief="flat",
                  font=FONT_BOLD, cursor="hand2", padx=10, pady=6,
                  command=self._load_midi).pack(fill="x")

        self._midi_label = tk.Label(p, text="Ningún archivo cargado",
                                    bg=COLORS["panel"], fg=COLORS["muted"],
                                    font=FONT_SMALL, wraplength=220)
        self._midi_label.pack(pady=(6, 12), anchor="w")

        # Metadata fields
        tk.Label(p, text="Author:", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=FONT_SMALL).pack(anchor="w")
        self._author_var = tk.StringVar()
        tk.Entry(p, textvariable=self._author_var, bg=COLORS["entry_bg"],
                 fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", font=FONT_BODY).pack(fill="x", pady=(2, 8))

        tk.Label(p, text="Estilo:", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=FONT_SMALL).pack(anchor="w")
        self._style_var = tk.StringVar()
        tk.Entry(p, textvariable=self._style_var, bg=COLORS["entry_bg"],
                 fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", font=FONT_BODY).pack(fill="x", pady=(2, 12))

        tk.Frame(p, bg=COLORS["border"], height=1).pack(fill="x", pady=6)

        # Track summary (populated after load)
        tk.Label(p, text="Tracks detectados:", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=FONT_SMALL).pack(anchor="w")

        self._track_info_frame = tk.Frame(p, bg=COLORS["panel"])
        self._track_info_frame.pack(fill="both", expand=True, pady=4)

        tk.Frame(p, bg=COLORS["border"], height=1).pack(fill="x", pady=6)

        # Global info
        tk.Label(p, text="Info global:", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=FONT_SMALL).pack(anchor="w")
        self._global_lbl = tk.Label(p, text="—", bg=COLORS["panel"],
                                    fg=COLORS["text"], font=FONT_SMALL,
                                    justify="left", wraplength=220)
        self._global_lbl.pack(anchor="w", pady=2)

        # Add derived track button
        tk.Frame(p, bg=COLORS["border"], height=1).pack(fill="x", pady=6)
        tk.Button(p, text="+ Agregar track derivado",
                  bg=COLORS["panel"], fg=COLORS["accent2"],
                  relief="flat", font=FONT_SMALL, cursor="hand2",
                  padx=6, pady=4,
                  command=self._add_derived_track).pack(fill="x")

    # ── Panel 2: Configurar tracks ──────────────────────────

    def _build_panel2(self, parent):
        p = tk.Frame(parent, bg=COLORS["bg"])
        p.grid(row=0, column=1, sticky="nsew", padx=4, pady=8)

        header = tk.Frame(p, bg=COLORS["bg"])
        header.pack(fill="x", pady=(0, 6))
        tk.Label(header, text="2 · Configurar arreglo",
                 bg=COLORS["bg"], fg=COLORS["accent"], font=FONT_TITLE).pack(side="left")

        tk.Frame(p, bg=COLORS["accent"], height=2).pack(fill="x", pady=(0, 8))

        # Scrollable area for track cards
        canvas = tk.Canvas(p, bg=COLORS["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(p, orient="vertical", command=canvas.yview)
        self._tracks_frame = tk.Frame(canvas, bg=COLORS["bg"])

        self._tracks_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas_window = canvas.create_window((0, 0), window=self._tracks_frame, anchor="nw")
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Mouse wheel scroll
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self._canvas = canvas

        # Placeholder
        self._placeholder = tk.Label(self._tracks_frame,
                                     text="Cargá un archivo MIDI para comenzar.",
                                     bg=COLORS["bg"], fg=COLORS["muted"],
                                     font=FONT_BODY, pady=40)
        self._placeholder.pack()

    # ── Panel 3: Generar y exportar ─────────────────────────

    def _build_panel3(self, parent):
        p = tk.Frame(parent, bg=COLORS["panel"], padx=12, pady=12)
        p.grid(row=0, column=2, sticky="nsew", padx=(4, 8), pady=8)

        tk.Label(p, text="3 · Generar y exportar",
                 bg=COLORS["panel"], fg=COLORS["accent"], font=FONT_TITLE).pack(anchor="w")
        tk.Frame(p, bg=COLORS["accent"], height=2).pack(fill="x", pady=(2, 10))

        # Preview YAML button
        tk.Button(p, text="Vista previa YAML",
                  bg=COLORS["card"], fg=COLORS["text"], relief="flat",
                  font=FONT_SMALL, cursor="hand2", padx=8, pady=4,
                  command=self._show_yaml_preview).pack(fill="x", pady=(0, 4))

        # Save YAML button
        tk.Button(p, text="Guardar YAML",
                  bg=COLORS["card"], fg=COLORS["text"], relief="flat",
                  font=FONT_SMALL, cursor="hand2", padx=8, pady=4,
                  command=self._save_yaml).pack(fill="x", pady=(0, 4))

        # Save to history button
        tk.Button(p, text="📁  Guardar en historial",
                  bg=COLORS["card"], fg=COLORS["accent2"], relief="flat",
                  font=FONT_SMALL, cursor="hand2", padx=8, pady=4,
                  command=self._save_to_history).pack(fill="x", pady=(0, 4))

        tk.Frame(p, bg=COLORS["border"], height=1).pack(fill="x", pady=8)

        # Run pipeline
        tk.Button(p, text="▶  Generar MIDI",
                  bg=COLORS["accent"], fg="white", relief="flat",
                  font=FONT_BOLD, cursor="hand2", padx=8, pady=8,
                  command=self._run_pipeline).pack(fill="x")

        # Progress bar
        self._progress = ttk.Progressbar(p, mode="indeterminate")
        self._progress.pack(fill="x", pady=(6, 0))

        tk.Frame(p, bg=COLORS["border"], height=1).pack(fill="x", pady=8)

        # Log
        tk.Label(p, text="Log:", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=FONT_SMALL).pack(anchor="w")
        self._log = scrolledtext.ScrolledText(
            p, height=10, bg=COLORS["bg"], fg=COLORS["accent2"],
            font=FONT_MONO, relief="flat", state="disabled",
            wrap="word"
        )
        self._log.pack(fill="both", expand=True, pady=(4, 0))

        tk.Frame(p, bg=COLORS["border"], height=1).pack(fill="x", pady=8)

        # ── History panel ────────────────────────────────────
        hist_header = tk.Frame(p, bg=COLORS["panel"])
        hist_header.pack(fill="x")

        tk.Label(hist_header, text="Historial de YAMLs:", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=FONT_SMALL).pack(side="left")

        tk.Button(hist_header, text="Abrir carpeta",
                  bg=COLORS["panel"], fg=COLORS["accent"], relief="flat",
                  font=FONT_SMALL, cursor="hand2",
                  command=self._open_history_folder).pack(side="right")

        tk.Button(hist_header, text="Eliminar",
                  bg=COLORS["panel"], fg=COLORS["danger"], relief="flat",
                  font=FONT_SMALL, cursor="hand2",
                  command=self._delete_history_item).pack(side="right", padx=4)

        list_frame = tk.Frame(p, bg=COLORS["panel"])
        list_frame.pack(fill="x", pady=(4, 0))

        scrollbar_h = tk.Scrollbar(list_frame, orient="vertical",
                                   bg=COLORS["panel"], troughcolor=COLORS["bg"])

        self._history_list = tk.Listbox(
            list_frame, height=6,
            bg=COLORS["bg"], fg=COLORS["text"],
            selectbackground=COLORS["accent"], selectforeground="white",
            font=FONT_SMALL, relief="flat", activestyle="none",
            yscrollcommand=scrollbar_h.set
        )
        scrollbar_h.config(command=self._history_list.yview)
        scrollbar_h.pack(side="right", fill="y")
        self._history_list.pack(side="left", fill="x", expand=True)
        self._history_list.bind("<Double-Button-1>", lambda e: self._open_history_item())

        # Output MIDI path label
        self._output_lbl = tk.Label(p, text="", bg=COLORS["panel"],
                                    fg=COLORS["accent2"], font=FONT_SMALL,
                                    wraplength=240, justify="left")
        self._output_lbl.pack(anchor="w", pady=(6, 0))

    # ── Logic: Load MIDI ────────────────────────────────────

    def _load_midi(self):
        path = filedialog.askopenfilename(
            title="Seleccionar archivo MIDI",
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")]
        )
        if not path:
            return

        self._midi_path = path
        self._midi_label.config(text=os.path.basename(path), fg=COLORS["text"])
        self._log_write(f"Cargando: {path}\n")

        try:
            schema = midi_to_yaml_mod.parse_midi(
                path,
                author=self._author_var.get(),
                style=self._style_var.get(),
            )
        except Exception as e:
            messagebox.showerror("Error al parsear MIDI", str(e))
            self._log_write(f"ERROR: {e}\n")
            return

        self._schema = schema
        self._populate_track_info(schema)
        self._populate_track_cards(schema)

        g = schema.get("global", {})
        self._global_lbl.config(
            text=f"Tempo: {g.get('tempo_bpm', '?')} BPM\n"
                 f"Compás: {g.get('time_signature', '?')}\n"
                 f"Tonalidad: {g.get('key_signature', '?')}"
        )
        self._log_write(f"OK — {len(schema['tracks'])} track(s) detectados.\n")

    def _populate_track_info(self, schema):
        for w in self._track_info_frame.winfo_children():
            w.destroy()

        for t in schema["tracks"]:
            instr = t.get("instrument", {})
            text  = (f"  [{t['id']}] {t['label']}\n"
                     f"       {instr.get('gm_name','')}  ·  {t['note_count']} notas")
            lbl = tk.Label(self._track_info_frame, text=text,
                           bg=COLORS["panel"], fg=COLORS["text"],
                           font=FONT_SMALL, justify="left", anchor="w")
            lbl.pack(fill="x", pady=1)

    def _populate_track_cards(self, schema):
        # Clear existing
        for w in self._tracks_frame.winfo_children():
            w.destroy()
        self._track_cards = []

        track_ids = [t["id"] for t in schema["tracks"]]

        for t in schema["tracks"]:
            card = TrackCard(
                self._tracks_frame, t, track_ids,
                on_delete=lambda c: self._track_cards.remove(c)
            )
            card.pack(fill="x", pady=4, padx=4)
            self._track_cards.append(card)

    # ── Logic: Add derived track ─────────────────────────────

    def _add_derived_track(self):
        if not self._schema:
            messagebox.showwarning("Sin MIDI", "Primero cargá un archivo MIDI.")
            return

        existing_ids = [t["id"] for t in self._schema["tracks"]]
        new_id = max([c.get_data()["id"] for c in self._track_cards], default=0) + 1

        # New empty track derived from track 1 by default
        src_id = existing_ids[0] if existing_ids else 1
        new_track = {
            "id": new_id,
            "label": f"Track {new_id} (derivado)",
            "instrument": {"gm_number": 40, "gm_name": "Violin"},
            "vocal_range": {"lowest_note": "C4", "highest_note": "C5", "range_name": "Instrumental"},
            "dynamics": {"velocity_min": 80, "velocity_max": 80, "velocity_average": 80.0},
            "articulations": [],
            "note_count": 0,
            "source_track_id": src_id,
            "transformations": [],
        }

        track_ids = existing_ids + [new_id]
        card = TrackCard(self._tracks_frame, new_track, track_ids,
                         on_delete=lambda c: self._track_cards.remove(c))
        card.pack(fill="x", pady=4, padx=4)
        self._track_cards.append(card)
        self._log_write(f"Track {new_id} derivado agregado.\n")

    # ── Logic: Build schema from UI ─────────────────────────

    def _build_schema(self):
        if not self._schema:
            raise ValueError("Primero cargá un archivo MIDI.")

        schema = deepcopy(self._schema)
        # Update metadata
        schema["metadata"]["author"] = self._author_var.get()
        schema["metadata"]["style"]  = self._style_var.get()
        schema["metadata"]["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Rebuild tracks from cards
        schema["tracks"] = [card.get_data() for card in self._track_cards]
        return schema

    # ── Logic: YAML preview ─────────────────────────────────

    def _show_yaml_preview(self):
        try:
            schema = self._build_schema()
            yaml_str = build_yaml_str(schema)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        win = tk.Toplevel(self)
        win.title("Vista previa YAML")
        win.geometry("680x600")
        win.configure(bg=COLORS["bg"])

        tk.Label(win, text="YAML generado (editable):",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=FONT_SMALL).pack(anchor="w", padx=8, pady=(8, 2))

        txt = scrolledtext.ScrolledText(win, font=FONT_MONO,
                                        bg=COLORS["bg"], fg=COLORS["text"],
                                        insertbackground=COLORS["text"],
                                        relief="flat")
        txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        txt.insert("1.0", yaml_str)

        def copy_to_clipboard():
            self.clipboard_clear()
            self.clipboard_append(txt.get("1.0", "end"))
            messagebox.showinfo("Copiado", "YAML copiado al portapapeles.")

        tk.Button(win, text="Copiar al portapapeles",
                  bg=COLORS["accent"], fg="white", relief="flat",
                  font=FONT_SMALL, cursor="hand2", padx=8, pady=4,
                  command=copy_to_clipboard).pack(pady=(0, 8))

    # ── Logic: Save YAML ────────────────────────────────────

    def _save_yaml(self):
        try:
            schema = self._build_schema()
            yaml_str = build_yaml_str(schema)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        default_name = os.path.splitext(
            os.path.basename(self._midi_path or "arrangement"))[0] + "_arrangement.yaml"
        path = filedialog.asksaveasfilename(
            title="Guardar YAML",
            defaultextension=".yaml",
            initialfile=default_name,
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if not path:
            return

        with open(path, "w", encoding="utf-8") as f:
            f.write(yaml_str)
        self._log_write(f"YAML guardado → {path}\n")
        messagebox.showinfo("Guardado", f"YAML guardado en:\n{path}")

    # ── Logic: Run pipeline ─────────────────────────────────

    def _run_pipeline(self):
        if not self._midi_path:
            messagebox.showwarning("Sin MIDI", "Primero cargá un archivo MIDI.")
            return

        try:
            schema = self._build_schema()
            yaml_str = build_yaml_str(schema)
        except Exception as e:
            messagebox.showerror("Error al construir schema", str(e))
            return

        # Ask for output path
        default_name = os.path.splitext(os.path.basename(self._midi_path))[0] + "_arranged.mid"
        out_midi = filedialog.asksaveasfilename(
            title="Guardar MIDI resultante",
            defaultextension=".mid",
            initialfile=default_name,
            filetypes=[("MIDI files", "*.mid"), ("All files", "*.*")]
        )
        if not out_midi:
            return

        # Write YAML to a temp file
        tmp_yaml = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                               delete=False, encoding="utf-8")
        tmp_yaml.write(yaml_str)
        tmp_yaml.close()

        self._log_write(f"\n▶ Ejecutando pipeline...\n  MIDI: {self._midi_path}\n  Output: {out_midi}\n\n")
        self._progress.start(10)

        def worker():
            try:
                result = yaml_to_midi_mod.apply_arrangement(
                    self._midi_path, tmp_yaml.name, out_midi
                )
                self.after(0, lambda: self._pipeline_done(out_midi))
            except Exception as e:
                err = traceback.format_exc()
                self.after(0, lambda: self._pipeline_error(err))
            finally:
                os.unlink(tmp_yaml.name)

        threading.Thread(target=worker, daemon=True).start()

    def _pipeline_done(self, out_path):
        self._progress.stop()
        self._log_write(f"✅ MIDI generado → {out_path}\n")
        self._output_lbl.config(text=f"✅ {os.path.basename(out_path)}")
        if messagebox.askyesno("Listo", f"MIDI guardado en:\n{out_path}\n\n¿Abrir la carpeta?"):
            folder = os.path.dirname(os.path.abspath(out_path))
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder])
            else:
                subprocess.run(["xdg-open", folder])

    def _pipeline_error(self, err):
        self._progress.stop()
        self._log_write(f"ERROR:\n{err}\n")
        messagebox.showerror("Error en el pipeline", err[:500])

    # ── Logic: History ──────────────────────────────────────

    def _save_to_history(self):
        try:
            schema   = self._build_schema()
            yaml_str = build_yaml_str(schema)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        midi_base = os.path.splitext(
            os.path.basename(self._midi_path or "arrangement"))[0]
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"{midi_base}_{ts}.yaml"
        filepath  = os.path.join(HISTORY_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(yaml_str)

        label = f"{ts}  {filename}"
        self._history.append((label, filepath))
        self._history_list.insert(0, label)
        self._log_write(f"Historial → {filepath}\n")

    def _load_history_from_disk(self):
        """Load any existing .yaml files from yaml_history/ on startup."""
        if not os.path.isdir(HISTORY_DIR):
            return
        files = sorted(
            [f for f in os.listdir(HISTORY_DIR) if f.endswith(".yaml")],
            reverse=True
        )
        for fname in files:
            fpath = os.path.join(HISTORY_DIR, fname)
            self._history.append((fname, fpath))
            self._history_list.insert("end", fname)

    def _open_history_item(self):
        sel = self._history_list.curselection()
        if not sel:
            return
        idx   = sel[0]
        label = self._history_list.get(idx)
        # Find matching filepath
        match = next((fp for (lb, fp) in self._history if lb == label), None)
        if not match or not os.path.exists(match):
            messagebox.showwarning("No encontrado", f"Archivo no encontrado:\n{match}")
            return
        # Show in preview window
        with open(match, "r", encoding="utf-8") as f:
            content = f.read()
        win = tk.Toplevel(self)
        win.title(f"Historial — {os.path.basename(match)}")
        win.geometry("680x600")
        win.configure(bg=COLORS["bg"])
        tk.Label(win, text=match, bg=COLORS["bg"], fg=COLORS["muted"],
                 font=FONT_SMALL, wraplength=660).pack(anchor="w", padx=8, pady=(8, 2))
        txt = scrolledtext.ScrolledText(win, font=FONT_MONO,
                                        bg=COLORS["bg"], fg=COLORS["text"],
                                        insertbackground=COLORS["text"],
                                        relief="flat")
        txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        txt.insert("1.0", content)

    def _delete_history_item(self):
        sel = self._history_list.curselection()
        if not sel:
            return
        idx   = sel[0]
        label = self._history_list.get(idx)
        match = next((fp for (lb, fp) in self._history if lb == label), None)

        if not messagebox.askyesno("Eliminar", f"¿Eliminar del historial?\n{label}"):
            return

        if match and os.path.exists(match):
            os.remove(match)

        self._history = [(lb, fp) for (lb, fp) in self._history if lb != label]
        self._history_list.delete(idx)
        self._log_write(f"Eliminado del historial: {label}\n")

    def _open_history_folder(self):
        os.makedirs(HISTORY_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(HISTORY_DIR)
        elif sys.platform == "darwin":
            subprocess.run(["open", HISTORY_DIR])
        else:
            subprocess.run(["xdg-open", HISTORY_DIR])

    # ── Helpers ─────────────────────────────────────────────

    def _log_write(self, text):
        self._log.configure(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = MidiArrangerApp()
    app.mainloop()