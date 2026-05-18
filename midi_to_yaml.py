"""
midi_to_yaml.py
───────────────
Reads a MIDI file and outputs an arrangement YAML following the
MIDI Arrangement Schema v1.0.

Usage:
    python midi_to_yaml.py input.mid
    python midi_to_yaml.py input.mid --output arrangement.yaml
    python midi_to_yaml.py input.mid --output arrangement.yaml --author "Jane Doe" --style "baroque"

Dependencies:
    pip install music21 pretty_midi mido pyyaml
"""

import argparse
import sys
import os
import warnings
from datetime import datetime, timezone

import pretty_midi
import mido
import yaml


# ─────────────────────────────────────────────────────────────
# GM Instrument table (number → name)
# ─────────────────────────────────────────────────────────────

GM_INSTRUMENTS = {
    0: "Acoustic Grand Piano", 1: "Bright Acoustic Piano", 2: "Electric Grand Piano",
    3: "Honky-tonk Piano", 4: "Electric Piano 1", 5: "Electric Piano 2",
    6: "Harpsichord", 7: "Clavi", 8: "Celesta", 9: "Glockenspiel",
    10: "Music Box", 11: "Vibraphone", 12: "Marimba", 13: "Xylophone",
    14: "Tubular Bells", 15: "Dulcimer", 16: "Drawbar Organ", 17: "Percussive Organ",
    18: "Rock Organ", 19: "Church Organ", 20: "Reed Organ", 21: "Accordion",
    22: "Harmonica", 23: "Tango Accordion", 24: "Acoustic Guitar (nylon)",
    25: "Acoustic Guitar (steel)", 26: "Electric Guitar (jazz)",
    27: "Electric Guitar (clean)", 28: "Electric Guitar (muted)",
    29: "Overdriven Guitar", 30: "Distortion Guitar", 31: "Guitar harmonics",
    32: "Acoustic Bass", 33: "Electric Bass (finger)", 34: "Electric Bass (pick)",
    35: "Fretless Bass", 36: "Slap Bass 1", 37: "Slap Bass 2",
    38: "Synth Bass 1", 39: "Synth Bass 2", 40: "Violin", 41: "Viola",
    42: "Cello", 43: "Contrabass", 44: "Tremolo Strings",
    45: "Pizzicato Strings", 46: "Orchestral Harp", 47: "Timpani",
    48: "String Ensemble 1", 49: "String Ensemble 2", 50: "SynthStrings 1",
    51: "SynthStrings 2", 52: "Choir Aahs", 53: "Voice Oohs", 54: "Synth Voice",
    55: "Orchestra Hit", 56: "Trumpet", 57: "Trombone", 58: "Tuba",
    59: "Muted Trumpet", 60: "French Horn", 61: "Brass Section",
    62: "SynthBrass 1", 63: "SynthBrass 2", 64: "Soprano Sax",
    65: "Alto Sax", 66: "Tenor Sax", 67: "Baritone Sax", 68: "Oboe",
    69: "English Horn", 70: "Bassoon", 71: "Clarinet", 72: "Piccolo",
    73: "Flute", 74: "Recorder", 75: "Pan Flute", 76: "Blown Bottle",
    77: "Shakuhachi", 78: "Whistle", 79: "Ocarina", 80: "Lead 1 (square)",
    81: "Lead 2 (sawtooth)", 82: "Lead 3 (calliope)", 83: "Lead 4 (chiff)",
    84: "Lead 5 (charang)", 85: "Lead 6 (voice)", 86: "Lead 7 (fifths)",
    87: "Lead 8 (bass+lead)", 88: "Pad 1 (new age)", 89: "Pad 2 (warm)",
    90: "Pad 3 (polysynth)", 91: "Pad 4 (choir)", 92: "Pad 5 (bowed)",
    93: "Pad 6 (metallic)", 94: "Pad 7 (halo)", 95: "Pad 8 (sweep)",
    96: "FX 1 (rain)", 97: "FX 2 (soundtrack)", 98: "FX 3 (crystal)",
    99: "FX 4 (atmosphere)", 100: "FX 5 (brightness)", 101: "FX 6 (goblins)",
    102: "FX 7 (echoes)", 103: "FX 8 (sci-fi)", 104: "Sitar", 105: "Banjo",
    106: "Shamisen", 107: "Koto", 108: "Kalimba", 109: "Bag pipe",
    110: "Fiddle", 111: "Shanai", 112: "Tinkle Bell", 113: "Agogo",
    114: "Steel Drums", 115: "Woodblock", 116: "Taiko Drum",
    117: "Melodic Tom", 118: "Synth Drum", 119: "Reverse Cymbal",
    120: "Guitar Fret Noise", 121: "Breath Noise", 122: "Seashore",
    123: "Bird Tweet", 124: "Telephone Ring", 125: "Helicopter",
    126: "Applause", 127: "Gunshot",
}


# ─────────────────────────────────────────────────────────────
# Vocal range detection
# ─────────────────────────────────────────────────────────────

# Standard vocal ranges as MIDI note numbers
# (lowest, highest) inclusive
VOCAL_RANGES = [
    ("Soprano",   60, 84),   # C4 – C6
    ("Mezzo",     57, 81),   # A3 – A5
    ("Alto",      53, 77),   # F3 – F5
    ("Tenor",     48, 72),   # C3 – C5
    ("Baritone",  45, 69),   # A2 – A4
    ("Bass",      40, 64),   # E2 – E4
]


def midi_note_to_name(midi_number: int) -> str:
    """Convert MIDI note number to scientific pitch notation (e.g. 60 → C4)."""
    note_names = ["C", "C#", "D", "D#", "E", "F",
                  "F#", "G", "G#", "A", "A#", "B"]
    octave = (midi_number // 12) - 1
    name = note_names[midi_number % 12]
    return f"{name}{octave}"


def detect_vocal_range(lowest_midi: int, highest_midi: int) -> str:
    """
    Heuristic: find the named vocal range whose span best contains
    the track's note range. Falls back to 'Instrumental' if no match.
    """
    best_match = None
    best_overlap = -1

    for range_name, r_low, r_high in VOCAL_RANGES:
        overlap_low = max(lowest_midi, r_low)
        overlap_high = min(highest_midi, r_high)
        overlap = max(0, overlap_high - overlap_low)
        coverage = overlap / max(1, (highest_midi - lowest_midi))
        if coverage > best_overlap:
            best_overlap = coverage
            best_match = range_name

    # Require at least 50% of the track's range to fall inside the vocal range
    if best_overlap < 0.5:
        return "Instrumental"
    return best_match


# ─────────────────────────────────────────────────────────────
# Key signature detection (simple heuristic via pitch class)
# ─────────────────────────────────────────────────────────────

KEY_PROFILES_MAJOR = {
    "C major":  [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88],
    "G major":  [2.88,6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29],
    "D major":  [2.29,2.88,6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66],
    "A major":  [3.66,2.29,2.88,6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39],
    "E major":  [2.39,3.66,2.29,2.88,6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19],
    "B major":  [5.19,2.39,3.66,2.29,2.88,6.35,2.23,3.48,2.33,4.38,4.09,2.52],
    "F# major": [2.52,5.19,2.39,3.66,2.29,2.88,6.35,2.23,3.48,2.33,4.38,4.09],
    "Db major": [4.09,2.52,5.19,2.39,3.66,2.29,2.88,6.35,2.23,3.48,2.33,4.38],
    "Ab major": [4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88,6.35,2.23,3.48,2.33],
    "Eb major": [3.48,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88,6.35,2.23,3.48],
    "Bb major": [2.23,3.48,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88,6.35,2.23],
    "F major":  [6.35,2.23,3.48,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88,6.35],
    "A minor":  [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17],
    "E minor":  [3.17,6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34],
    "B minor":  [3.34,3.17,6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69],
    "F# minor": [2.69,3.34,3.17,6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98],
    "C# minor": [3.98,2.69,3.34,3.17,6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75],
    "G# minor": [4.75,3.98,2.69,3.34,3.17,6.33,2.68,3.52,5.38,2.60,3.53,2.54],
    "D# minor": [2.54,4.75,3.98,2.69,3.34,3.17,6.33,2.68,3.52,5.38,2.60,3.53],
    "Bb minor": [3.53,2.54,4.75,3.98,2.69,3.34,3.17,6.33,2.68,3.52,5.38,2.60],
    "F minor":  [2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17,6.33,2.68,3.52,5.38],
    "C minor":  [5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17,6.33,2.68,3.52],
    "G minor":  [3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17,6.33,2.68],
    "D minor":  [2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17,6.33],
}


def detect_key_signature(midi_path: str, midi_obj: pretty_midi.PrettyMIDI) -> str:
    """
    Detect the key signature.

    Priority:
      1. key_signature meta-event embedded in the MIDI (most reliable).
      2. Krumhansl-Schmuckler pitch-class correlation (fallback for MIDIs
         without key meta-events, e.g. hand-crafted files).

    The meta-event uses a short format like 'C', 'Cm', 'F#', 'Bbm', etc.
    We expand it to the full form used in our schema ('C major', 'C minor').
    """
    # ── 1. Try meta-event first ──────────────────────────────
    try:
        mid = mido.MidiFile(midi_path)
        for track in mid.tracks:
            for msg in track:
                if msg.type == "key_signature":
                    key = msg.key          # e.g. 'C', 'Cm', 'F#', 'Bbm'
                    if key.endswith("m"):
                        return f"{key[:-1]} minor"
                    else:
                        return f"{key} major"
    except Exception:
        pass

    # ── 2. Krumhansl-Schmuckler fallback ─────────────────────
    pitch_counts = [0.0] * 12
    for instrument in midi_obj.instruments:
        if instrument.is_drum:
            continue
        for note in instrument.notes:
            pitch_counts[note.pitch % 12] += note.end - note.start

    total = sum(pitch_counts) or 1.0
    pitch_dist = [c / total for c in pitch_counts]

    best_key = "Unknown"
    best_score = float("-inf")

    for key_name, profile in KEY_PROFILES_MAJOR.items():
        score = sum(p * q for p, q in zip(pitch_dist, profile))
        if score > best_score:
            best_score = score
            best_key = key_name

    return best_key


# ─────────────────────────────────────────────────────────────
# Articulation detection
# ─────────────────────────────────────────────────────────────

def detect_articulations(notes: list) -> list[str]:
    """
    Heuristic articulation detection based on note duration
    and inter-onset intervals.

    Thresholds (in seconds, assuming quarter-note ≈ 0.5s at 120 BPM):
      - staccato : avg duration < 0.1s  (very short, detached)
      - legato   : avg gap between notes < 0.02s (nearly connected)
      - tenuto   : avg duration > 0.4s and not staccato (held, full value)
      - natural  : none of the above

    Returns a list of detected articulation tags.
    """
    if not notes:
        return []

    articulations = set()
    durations = [n.end - n.start for n in notes]
    avg_dur = sum(durations) / len(durations)

    # Staccato: average note duration is very short (< 0.1s)
    if avg_dur < 0.1:
        articulations.add("staccato")

    # Legato: very small average gap between consecutive notes
    sorted_notes = sorted(notes, key=lambda n: n.start)
    gaps = [
        sorted_notes[i].start - sorted_notes[i - 1].end
        for i in range(1, len(sorted_notes))
    ]
    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        if avg_gap < 0.02:
            articulations.add("legato")

    # Tenuto: notes held at full value (avg > 0.4s) and not staccato
    if avg_dur > 0.4 and "staccato" not in articulations:
        articulations.add("tenuto")

    return sorted(articulations) if articulations else ["natural"]


# ─────────────────────────────────────────────────────────────
# Time signature extraction
# ─────────────────────────────────────────────────────────────

def get_time_signature(midi_path: str, midi_obj: pretty_midi.PrettyMIDI) -> str:
    """
    Return the musical time signature of the piece.

    Some DAWs (e.g. MuseScore) emit a fake 1/4 or 1/1 time_signature at
    tick=0 as a pickup-beat marker, followed by the real time signature one
    beat later.  Strategy: collect ALL time_signature meta-events across all
    tracks, then return the one that appears most often (majority vote).
    On a tie, prefer the last one before the first note event.
    Falls back to pretty_midi, then to '4/4'.
    """
    try:
        mid = mido.MidiFile(midi_path)

        # Collect (tick_absolute, numerator, denominator)
        ts_events = []
        for track in mid.tracks:
            tick = 0
            for msg in track:
                tick += msg.time
                if msg.type == "time_signature":
                    ts_events.append((tick, msg.numerator, msg.denominator))

        if ts_events:
            # Majority vote on (numerator, denominator) pairs
            from collections import Counter
            votes = Counter((n, d) for _, n, d in ts_events)
            # Exclude 1/x signatures — these are almost always pickup markers
            real_votes = Counter({k: v for k, v in votes.items() if k[0] != 1})
            chosen = (real_votes or votes).most_common(1)[0][0]
            return f"{chosen[0]}/{chosen[1]}"
    except Exception:
        pass

    # Fallback: pretty_midi
    if midi_obj.time_signature_changes:
        ts = midi_obj.time_signature_changes[0]
        return f"{ts.numerator}/{ts.denominator}"

    return "4/4"


# ─────────────────────────────────────────────────────────────
# Instruments that are never vocal — always "Instrumental"
# ─────────────────────────────────────────────────────────────

# GM numbers of instruments that have no vocal-range analogue.
# Piano family (0-7), chromatic perc (8-15), organs (16-23),
# guitars (24-31), basses (32-39), all drums (128).
NON_VOCAL_GM = set(range(0, 40)) | {128}

# GM numbers that ARE melodic but not vocals — still useful to
# detect range for transposition purposes; we label them "Instrumental"
# regardless of pitch overlap with vocal ranges.
ALWAYS_INSTRUMENTAL_GM = set(range(0, 40)) | set(range(112, 128)) | {128}


def is_vocal_instrument(gm_number: int) -> bool:
    """Return True only for instruments that can plausibly match a vocal range."""
    return gm_number not in ALWAYS_INSTRUMENTAL_GM


# ─────────────────────────────────────────────────────────────
# Label deduplication within a file
# ─────────────────────────────────────────────────────────────

def deduplicate_labels(tracks: list[dict]) -> list[dict]:
    """
    If multiple tracks share the same label, append ' 1', ' 2', … suffixes.
    Also detects Piano right/left hand splits by pitch register.
    """
    from collections import Counter

    label_counts: Counter = Counter(t["label"] for t in tracks)
    label_seen: Counter = Counter()

    # Piano hand split: if two tracks share a Piano label, name them by register
    piano_tracks = [t for t in tracks if "Piano" in t["label"]]
    if len(piano_tracks) == 2:
        pitches_0 = _avg_pitch_from_label(piano_tracks[0])
        pitches_1 = _avg_pitch_from_label(piano_tracks[1])
        high, low = (piano_tracks[0], piano_tracks[1]) if pitches_0 >= pitches_1 \
                    else (piano_tracks[1], piano_tracks[0])
        high["label"] = high["label"].replace("Piano", "Piano - Right Hand")
        low["label"]  = low["label"].replace("Piano", "Piano - Left Hand")
        label_counts = Counter(t["label"] for t in tracks)

    for track in tracks:
        lbl = track["label"]
        if label_counts[lbl] > 1:
            label_seen[lbl] += 1
            track["label"] = f"{lbl} {label_seen[lbl]}"

    return tracks


def _avg_pitch_from_label(track: dict) -> float:
    """Helper: return midpoint of lowest/highest note for sorting."""
    low = track["vocal_range"]["lowest_note"]
    high = track["vocal_range"]["highest_note"]
    return (_name_to_midi(low) + _name_to_midi(high)) / 2


def _name_to_midi(name: str) -> int:
    """Inverse of midi_note_to_name: 'C4' → 60."""
    note_map = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
                "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    if len(name) >= 3 and name[1] == "#":
        note, octave = name[:2], int(name[2:])
    else:
        note, octave = name[0], int(name[1:])
    return (octave + 1) * 12 + note_map[note]


def velocity_stats(notes: list) -> dict:
    """Return min, max, and average velocity for a list of notes."""
    if not notes:
        return {"min": 0, "max": 0, "average": 0}
    velocities = [n.velocity for n in notes]
    return {
        "min": int(min(velocities)),
        "max": int(max(velocities)),
        "average": round(sum(velocities) / len(velocities), 1),
    }


# ─────────────────────────────────────────────────────────────
# Main parser
# ─────────────────────────────────────────────────────────────

def parse_midi(
    midi_path: str,
    author: str = "",
    style: str = "",
) -> dict:
    """
    Parse a MIDI file and return the arrangement schema as a dict.

    Args:
        midi_path: Path to the .mid / .midi file.
        author:    Optional attribution string.
        style:     Optional musical style tag.

    Returns:
        Dict ready to be serialised to YAML.
    """
    if not os.path.exists(midi_path):
        raise FileNotFoundError(f"MIDI file not found: {midi_path}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        midi_obj = pretty_midi.PrettyMIDI(midi_path)

    # ── Global info ──────────────────────────────────────────
    tempo_estimates = midi_obj.get_tempo_changes()
    if len(tempo_estimates[1]) > 0:
        tempo_bpm = round(float(tempo_estimates[1][0]), 2)
    else:
        tempo_bpm = 120.0

    time_sig = get_time_signature(midi_path, midi_obj)
    key_sig = detect_key_signature(midi_path, midi_obj)

    # ── Tracks ───────────────────────────────────────────────
    tracks = []
    track_id = 1

    for instrument in midi_obj.instruments:
        notes = instrument.notes
        if not notes:
            continue  # skip empty tracks

        # Pitch range
        pitches = [n.pitch for n in notes]
        lowest_midi = min(pitches)
        highest_midi = max(pitches)
        lowest_name = midi_note_to_name(lowest_midi)
        highest_name = midi_note_to_name(highest_midi)

        # Instrument name
        if instrument.is_drum:
            gm_number = 128  # convention for percussion
            gm_name = "Drumkit"
        else:
            gm_number = instrument.program
            gm_name = GM_INSTRUMENTS.get(gm_number, f"Unknown ({gm_number})")

        # Vocal range: only assign SATB names for melodic/vocal instruments
        if is_vocal_instrument(gm_number):
            range_name = detect_vocal_range(lowest_midi, highest_midi)
        else:
            range_name = "Instrumental"

        # Dynamics
        vel = velocity_stats(notes)

        # Articulations
        articulations = detect_articulations(notes)

        track = {
            "id": track_id,
            "label": instrument.name if instrument.name.strip() else gm_name,
            "instrument": {
                "gm_number": int(gm_number),
                "gm_name": gm_name,
            },
            "vocal_range": {
                "lowest_note": lowest_name,
                "highest_note": highest_name,
                "range_name": range_name,
            },
            "dynamics": {
                "velocity_min": vel["min"],
                "velocity_max": vel["max"],
                "velocity_average": vel["average"],
            },
            "articulations": articulations,
            "note_count": len(notes),
            "transformations": [],  # user fills this in
        }

        tracks.append(track)
        track_id += 1

    # Deduplicate labels (e.g. Piano → Piano - Right Hand / Left Hand)
    tracks = deduplicate_labels(tracks)

    # ── Assemble schema ──────────────────────────────────────
    schema = {
        "metadata": {
            "schema_version": "1.0",
            "source_file": os.path.basename(midi_path),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "author": author,
            "style": style,
        },
        "global": {
            "tempo_bpm": tempo_bpm,
            "time_signature": time_sig,
            "key_signature": key_sig,
        },
        "tracks": tracks,
    }

    return schema


# ─────────────────────────────────────────────────────────────
# YAML serialisation
# ─────────────────────────────────────────────────────────────

class _IndentedListDumper(yaml.Dumper):
    """Custom YAML dumper: indent list items for readability."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


def schema_to_yaml(schema: dict) -> str:
    """Serialise the schema dict to a pretty-printed YAML string."""
    return yaml.dump(
        schema,
        Dumper=_IndentedListDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parse a MIDI file and output an arrangement YAML."
    )
    parser.add_argument("midi_file", help="Path to the input .mid file")
    parser.add_argument(
        "--output", "-o",
        help="Output YAML path (default: <midi_name>.yaml)",
        default=None,
    )
    parser.add_argument("--author", default="", help="Author attribution")
    parser.add_argument("--style", default="", help="Musical style tag (e.g. baroque)")

    args = parser.parse_args()

    # Resolve output path
    if args.output:
        output_path = args.output
    else:
        base = os.path.splitext(args.midi_file)[0]
        output_path = base + ".yaml"

    print(f"Parsing: {args.midi_file}")
    schema = parse_midi(args.midi_file, author=args.author, style=args.style)
    yaml_str = schema_to_yaml(schema)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(yaml_str)

    print(f"YAML written to: {output_path}")
    print()
    print(yaml_str)


if __name__ == "__main__":
    main()