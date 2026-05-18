# MIDI Arranger

Sistema de automatización de arreglos musicales basado en YAML.  
Convierte archivos `.mid` en arreglos editables, aplica transformaciones y genera un nuevo `.mid`.

---

## Archivos del proyecto

```
proyecto/
  ├── midi_arranger.py        ← GUI principal (este programa)
  ├── midi_to_yaml.py         ← Analiza un .mid y genera el YAML base
  ├── yaml_to_midi.py         ← Aplica el YAML de arreglo y genera el .mid final
  ├── benchmark_arrangement.py← Mide rendimiento y consistencia del pipeline
  └── README.md
```

---

## Instalación

Python 3.10 o superior. Tkinter viene incluido en la instalación estándar de Python.

```bash
pip install pretty_midi mido pyyaml
```

---

## Uso rápido

```bash
python midi_arranger.py
```

---

## Flujo completo

```
archivo.mid
    │
    ▼
midi_to_yaml.py          ← analiza el MIDI: detecta tracks, instrumento,
    │                       tempo, compás, tonalidad, articulaciones
    ▼
arrangement.yaml         ← el usuario edita: agrega transformaciones,
    │                       tracks derivados, cambios de instrumento
    ▼
yaml_to_midi.py          ← aplica el arreglo sobre el MIDI original
    │
    ▼
archivo_arranged.mid     ← resultado final listo para reproducir
```

---

## La GUI — Panel a panel

### Panel 1 · Cargar MIDI

1. Hacé clic en **Seleccionar archivo .mid** y elegí tu archivo.
2. La app llama automáticamente a `midi_to_yaml.parse_midi()` y detecta:
   - Cantidad de tracks y su instrumento GM
   - Rango de notas (más baja / más alta)
   - Velocidad mínima, máxima y promedio
   - Tempo, compás y tonalidad
3. Completá **Author** y **Estilo** (opcional, se guardan en el YAML).
4. El botón **+ Agregar track derivado** crea un track nuevo basado en uno existente (útil para agregar una voz extra como violín o flauta).

### Panel 2 · Configurar arreglo

Cada track del MIDI aparece como una tarjeta editable:

| Campo | Descripción |
|---|---|
| Label | Nombre del track (editable) |
| Fuente | `(mismo track)` o el ID de otro track del que copiar notas |
| Instrumento | Dropdown con los 128 instrumentos GM |
| Transformaciones | Lista ordenada de efectos a aplicar |

#### Transformaciones disponibles

| Tipo | Parámetros | Efecto |
|---|---|---|
| `transpose` | `semitones` | Sube o baja el tono N semitonos |
| `instrument_change` | `to_gm` | Cambia el instrumento (número GM 0–127) |
| `velocity_scale` | `factor` | Multiplica la velocidad (ej. 0.75 = más suave) |
| `velocity_set` | `value` | Fija la velocidad a un valor fijo (0–127) |
| `reverse` | — | Invierte el orden de las notas |
| `augment` | `duration_factor` | Alarga las notas (ej. 2.0 = el doble) |
| `diminish` | `duration_factor` | Acorta las notas (ej. 0.5 = la mitad) |
| `invert` | `pivot_midi` | Inversión melódica alrededor de una nota pivot |
| `humanize` | `timing_ms`, `velocity_variance` | Agrega variación aleatoria (⚠ no determinista) |

> **Nota sobre determinismo:** todas las transformaciones producen el mismo resultado en cada ejecución, excepto `humanize`, que usa números aleatorios para simular expresividad humana. Si necesitás reproducibilidad exacta (para benchmarks o el paper), no uses `humanize`.

Podés agregar múltiples transformaciones por track — se aplican en orden de arriba hacia abajo.

### Panel 3 · Generar y exportar

| Botón | Acción |
|---|---|
| **Vista previa YAML** | Abre una ventana con el YAML generado, editable y copiable |
| **Guardar YAML** | Guarda el YAML en disco (sin ejecutar el pipeline) |
| **Guardar en historial** | Guarda el YAML en la carpeta `yaml_history/` con timestamp |
| **▶ Generar MIDI** | Ejecuta el pipeline completo y guarda el `.mid` resultante |

El pipeline corre en un hilo separado para que la interfaz no se congele. El log muestra el progreso en tiempo real.

---

## Uso por línea de comandos (sin GUI)

### Paso 1 — MIDI → YAML

```bash
python midi_to_yaml.py archivo.mid
python midi_to_yaml.py archivo.mid --output arreglo.yaml --author "Jane Doe" --style "baroque"
```

### Paso 2 — Editar el YAML

Abrí el `.yaml` generado y agregá transformaciones a cada track:

```yaml
tracks:
  - id: 1
    label: Piano - Right Hand
    instrument:
      gm_number: 0
      gm_name: Acoustic Grand Piano
    transformations:
      - type: transpose
        semitones: 7
        reason: "Quinta arriba"
      - type: velocity_scale
        factor: 0.9
```

### Paso 3 — YAML → MIDI

```bash
python yaml_to_midi.py archivo.mid arreglo.yaml --output resultado.mid
```

---

## Benchmark de rendimiento

```bash
# 100 corridas
python benchmark_arrangement.py archivo.mid arreglo.yaml --runs 100

# 1000 corridas
python benchmark_arrangement.py archivo.mid arreglo.yaml --runs 1000
```

Genera estadísticas de tiempo (mean, median, std dev, p95, p99) y verifica consistencia del output mediante SHA256. Los resultados se exportan a un `.csv` listo para graficar.

### Resultados de referencia (Prueba1.mid, 4 tracks, sin humanize)

| Métrica | 100 runs | 1000 runs |
|---|---|---|
| Media | 11.08 ms | 8.58 ms |
| Mediana | 10.08 ms | 8.38 ms |
| Std dev | 4.68 ms | 1.03 ms |
| p95 | 15.44 ms | 10.13 ms |
| p99 | 50.81 ms | 11.83 ms |
| Outputs únicos | 1/100 ✅ | 1/1000 ✅ |
| SHA256 | `f33bb477...` | `f33bb477...` (idéntico) |

---

## Esquema YAML — referencia

```yaml
metadata:
  schema_version: '1.0'
  source_file: archivo.mid
  created_at: '2026-05-14T00:00:00Z'
  author: Jane Doe
  style: baroque

global:
  tempo_bpm: 132.0
  time_signature: 3/4
  key_signature: C major

tracks:
  - id: 1
    label: Piano - Right Hand
    instrument:
      gm_number: 0
      gm_name: Acoustic Grand Piano
    vocal_range:
      lowest_note: C4
      highest_note: C5
      range_name: Instrumental
    dynamics:
      velocity_min: 80
      velocity_max: 80
      velocity_average: 80.0
    articulations:
      - legato
    note_count: 128
    transformations:
      - type: transpose
        semitones: 7
        reason: "Quinta arriba"

  # Track derivado — copia las notas del track 1 y aplica sus propias transformaciones
  - id: 3
    source_track_id: 1
    label: Violin - Contrapunto
    instrument:
      gm_number: 40
      gm_name: Violin
    transformations:
      - type: transpose
        semitones: 12
      - type: velocity_scale
        factor: 0.75
```

---

## Dependencias

| Librería | Uso |
|---|---|
| `pretty_midi` | Análisis y síntesis de archivos MIDI |
| `mido` | Lectura de meta-eventos MIDI (key signature, time signature) |
| `pyyaml` | Serialización y deserialización del YAML de arreglo |
| `tkinter` | GUI de escritorio (incluido en Python estándar) |

---

## Créditos

