"""
yaml_to_midi.py
───────────────
Reads an original MIDI + an edited arrangement YAML and produces a
new MIDI with all the requested transformations applied.

Usage:
    python yaml_to_midi.py input.mid arrangement.yaml
    python yaml_to_midi.py input.mid arrangement.yaml --output output.mid

Supported transformation types (set in the YAML transformations list):

    transpose
        semitones: int          # negative = down, positive = up
                                # ±12 = one octave, ±24 = two octaves

    instrument_change
        to_gm: int              # target GM program number (0-127)

    velocity_scale
        factor: float           # 0.5 = half volume, 2.0 = double (clamped 1-127)

    velocity_set
        value: int              # force all notes to this velocity (1-127)

    reverse
        (no params)             # reverse the note sequence in time

    augment
        duration_factor: float  # stretch note durations (e.g. 2.0 = double length)

    diminish
        duration_factor: float  # shrink note durations (e.g. 0.5 = half length)

    invert
        pivot_midi: int         # mirror pitches around this MIDI note
                                # (e.g. 60 = C4)

    humanize
        timing_ms: float        # max random timing offset in milliseconds (e.g. 15)
        velocity_variance: int  # max random velocity offset (e.g. 8)

Example YAML transformation block:
    transformations:
      - type: transpose
        semitones: 12
        reason: "Octave up for brightness"
      - type: instrument_change
        to_gm: 73
        reason: "Switch to Flute"
      - type: velocity_scale
        factor: 0.8
        reason: "Slightly softer"

Dependencies:
    pip install pretty_midi mido pyyaml
"""

import argparse
import os
import random
import sys
import warnings
from copy import deepcopy

import pretty_midi
import yaml


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_midi(path: str) -> pretty_midi.PrettyMIDI:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return pretty_midi.PrettyMIDI(path)


# ─────────────────────────────────────────────────────────────
# Individual transformation functions
# Each receives a list[pretty_midi.Note] and params dict,
# returns a new list[pretty_midi.Note].
# ─────────────────────────────────────────────────────────────

def tf_transpose(notes: list, params: dict) -> list:
    """Shift all pitches by N semitones. Clamps to MIDI range 0-127."""
    semitones = int(params.get("semitones", 0))
    result = []
    for n in notes:
        new_pitch = int(clamp(n.pitch + semitones, 0, 127))
        result.append(pretty_midi.Note(
            velocity=n.velocity,
            pitch=new_pitch,
            start=n.start,
            end=n.end,
        ))
    return result


def tf_instrument_change(notes: list, params: dict) -> list:
    """No-op on notes — instrument change is handled at track level."""
    return deepcopy(notes)


def tf_velocity_scale(notes: list, params: dict) -> list:
    """Multiply all velocities by factor. Clamps to 1-127."""
    factor = float(params.get("factor", 1.0))
    result = []
    for n in notes:
        new_vel = int(clamp(round(n.velocity * factor), 1, 127))
        result.append(pretty_midi.Note(
            velocity=new_vel,
            pitch=n.pitch,
            start=n.start,
            end=n.end,
        ))
    return result


def tf_velocity_set(notes: list, params: dict) -> list:
    """Force all notes to a fixed velocity."""
    value = int(clamp(params.get("value", 80), 1, 127))
    return [
        pretty_midi.Note(velocity=value, pitch=n.pitch, start=n.start, end=n.end)
        for n in notes
    ]


def tf_reverse(notes: list, params: dict) -> list:
    """
    Reverse the order of notes in time while preserving the overall
    time span (start of first note → end of last note).
    """
    if not notes:
        return []
    sorted_notes = sorted(notes, key=lambda n: n.start)
    total_start = sorted_notes[0].start
    total_end   = sorted_notes[-1].end

    result = []
    for n in reversed(sorted_notes):
        duration = n.end - n.start
        # Mirror the start position around the midpoint of the span
        new_start = total_start + (total_end - n.end)
        new_end   = new_start + duration
        result.append(pretty_midi.Note(
            velocity=n.velocity,
            pitch=n.pitch,
            start=round(new_start, 6),
            end=round(new_end, 6),
        ))
    return sorted(result, key=lambda n: n.start)


def tf_augment(notes: list, params: dict) -> list:
    """
    Stretch note durations and positions by duration_factor.
    The start of the first note is kept fixed; everything else scales.
    """
    factor = float(params.get("duration_factor", 2.0))
    if not notes:
        return []
    sorted_notes = sorted(notes, key=lambda n: n.start)
    origin = sorted_notes[0].start
    result = []
    for n in sorted_notes:
        new_start = origin + (n.start - origin) * factor
        new_end   = origin + (n.end   - origin) * factor
        result.append(pretty_midi.Note(
            velocity=n.velocity,
            pitch=n.pitch,
            start=round(new_start, 6),
            end=round(new_end, 6),
        ))
    return result


def tf_diminish(notes: list, params: dict) -> list:
    """
    Shrink note durations and positions by duration_factor.
    Delegates to augment with the inverse factor.
    """
    factor = float(params.get("duration_factor", 0.5))
    return tf_augment(notes, {"duration_factor": factor})


def tf_invert(notes: list, params: dict) -> list:
    """
    Melodic inversion: mirror each pitch around a pivot note.
    pivot_midi defaults to the mean pitch of the track.
    """
    if not notes:
        return []
    pivot = int(params.get("pivot_midi",
                           round(sum(n.pitch for n in notes) / len(notes))))
    result = []
    for n in notes:
        new_pitch = int(clamp(2 * pivot - n.pitch, 0, 127))
        result.append(pretty_midi.Note(
            velocity=n.velocity,
            pitch=new_pitch,
            start=n.start,
            end=n.end,
        ))
    return result


def tf_humanize(notes: list, params: dict) -> list:
    """
    Add subtle random timing and velocity offsets to make MIDI feel less robotic.
    timing_ms    : max offset in milliseconds (applied to start; end follows)
    velocity_variance : max ± velocity offset
    """
    timing_s  = float(params.get("timing_ms", 15)) / 1000.0
    vel_var   = int(params.get("velocity_variance", 8))
    result = []
    for n in notes:
        dt  = random.uniform(-timing_s, timing_s)
        dv  = random.randint(-vel_var, vel_var)
        dur = n.end - n.start
        new_start = max(0.0, n.start + dt)
        result.append(pretty_midi.Note(
            velocity=int(clamp(n.velocity + dv, 1, 127)),
            pitch=n.pitch,
            start=round(new_start, 6),
            end=round(new_start + dur, 6),
        ))
    return result


# ─────────────────────────────────────────────────────────────
# Transformation dispatcher
# ─────────────────────────────────────────────────────────────

TRANSFORMATIONS = {
    "transpose":          tf_transpose,
    "instrument_change":  tf_instrument_change,
    "velocity_scale":     tf_velocity_scale,
    "velocity_set":       tf_velocity_set,
    "reverse":            tf_reverse,
    "augment":            tf_augment,
    "diminish":           tf_diminish,
    "invert":             tf_invert,
    "humanize":           tf_humanize,
}


def apply_transformations(notes: list, transformations: list) -> list:
    """
    Apply a list of transformations in order to a note list.
    Unknown transformation types emit a warning and are skipped.
    """
    current = deepcopy(notes)
    for tf in transformations:
        tf_type = tf.get("type", "").lower()
        if tf_type not in TRANSFORMATIONS:
            print(f"  [WARNING] Unknown transformation type '{tf_type}' — skipped.")
            continue
        reason = tf.get("reason", "")
        label  = f"  → {tf_type}" + (f": {reason}" if reason else "")
        print(label)
        current = TRANSFORMATIONS[tf_type](current, tf)
    return current


# ─────────────────────────────────────────────────────────────
# Track builder
# ─────────────────────────────────────────────────────────────

def build_track(
    track_schema: dict,
    source_notes: list,
) -> pretty_midi.Instrument:
    """
    Build a pretty_midi Instrument from a track schema dict and
    a list of (already transformed) notes.
    """
    gm_number = track_schema["instrument"]["gm_number"]
    label     = track_schema.get("label", track_schema["instrument"]["gm_name"])
    is_drum   = (gm_number == 128)

    instrument = pretty_midi.Instrument(
        program=gm_number if not is_drum else 0,
        is_drum=is_drum,
        name=label,
    )
    instrument.notes = source_notes
    return instrument


# ─────────────────────────────────────────────────────────────
# Source track resolution
# ─────────────────────────────────────────────────────────────

def resolve_source_notes(
    track_schema: dict,
    original_tracks: list,          # list of pretty_midi.Instrument
    track_id_map: dict,             # {yaml_id: pretty_midi.Instrument}
) -> list:
    """
    Determine which notes feed this track:
      - If source_track_id is set → copy notes from that track
      - Otherwise → use the track with matching id from the original MIDI
    Returns a deep copy of the note list.
    """
    source_id = track_schema.get("source_track_id")
    own_id    = track_schema["id"]

    if source_id is not None:
        src = track_id_map.get(int(source_id))
        if src is None:
            raise ValueError(
                f"Track id={own_id} references source_track_id={source_id} "
                f"which does not exist in the MIDI."
            )
    else:
        src = track_id_map.get(int(own_id))
        if src is None:
            raise ValueError(
                f"Track id={own_id} has no matching track in the original MIDI. "
                f"If this is a new derived track, set source_track_id."
            )

    return deepcopy(src.notes)


# ─────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────

def apply_arrangement(
    midi_path: str,
    yaml_path: str,
    output_path: str,
) -> pretty_midi.PrettyMIDI:
    """
    Full pipeline:
      1. Load original MIDI + arrangement YAML
      2. For each track in the YAML:
         a. Resolve source notes (own track or derived from another)
         b. Apply transformations in order
         c. Apply instrument_change if present
      3. Write new MIDI

    Returns the resulting PrettyMIDI object.
    """
    print(f"\n{'─'*52}")
    print(f"  Source MIDI : {midi_path}")
    print(f"  Arrangement : {yaml_path}")
    print(f"  Output MIDI : {output_path}")
    print(f"{'─'*52}\n")

    # ── Load ──────────────────────────────────────────────────
    schema      = load_yaml(yaml_path)
    original    = load_midi(midi_path)

    # Build id→instrument map from original MIDI (1-indexed, skip empty)
    track_id_map: dict = {}
    idx = 1
    for inst in original.instruments:
        if inst.notes:
            track_id_map[idx] = inst
            idx += 1

    # ── Global settings ───────────────────────────────────────
    g = schema.get("global", {})
    tempo_bpm = float(g.get("tempo_bpm", 120.0))

    new_midi = pretty_midi.PrettyMIDI(initial_tempo=tempo_bpm)

    # ── Process each track ────────────────────────────────────
    for track_schema in schema.get("tracks", []):
        tid   = track_schema["id"]
        label = track_schema.get("label", f"Track {tid}")
        tfs   = track_schema.get("transformations", [])

        print(f"[Track {tid}] {label}")

        # Resolve source notes
        notes = resolve_source_notes(track_schema, original.instruments, track_id_map)

        # Resolve final GM number (may be overridden by instrument_change)
        gm_number = track_schema["instrument"]["gm_number"]
        for tf in tfs:
            if tf.get("type") == "instrument_change":
                gm_number = int(tf.get("to_gm", gm_number))
                # Patch back into schema so build_track picks it up
                track_schema = deepcopy(track_schema)
                track_schema["instrument"]["gm_number"] = gm_number

        if not tfs:
            print("  → no transformations (copied as-is)")

        # Apply transformations
        transformed_notes = apply_transformations(notes, tfs)

        if not transformed_notes:
            print(f"  [WARNING] Track {tid} produced 0 notes — skipped.")
            continue

        # Build instrument and add to new MIDI
        instrument = build_track(track_schema, transformed_notes)
        new_midi.instruments.append(instrument)

        # Summary
        pitches = [n.pitch for n in transformed_notes]
        print(f"  ✓ {len(transformed_notes)} notes  |  "
              f"pitch range {min(pitches)}–{max(pitches)}\n")

    # ── Write output ──────────────────────────────────────────
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    new_midi.write(output_path)
    print(f"{'─'*52}")
    print(f"  ✅ Written → {output_path}")
    print(f"{'─'*52}\n")

    return new_midi


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Apply arrangement transformations from YAML to a MIDI file."
    )
    parser.add_argument("midi_file",  help="Path to the original .mid file")
    parser.add_argument("yaml_file",  help="Path to the edited arrangement .yaml")
    parser.add_argument(
        "--output", "-o",
        help="Output MIDI path (default: <midi_name>_arranged.mid)",
        default=None,
    )
    args = parser.parse_args()

    if args.output:
        output_path = args.output
    else:
        base = os.path.splitext(args.midi_file)[0]
        output_path = base + "_arranged.mid"

    apply_arrangement(args.midi_file, args.yaml_file, output_path)


if __name__ == "__main__":
    main()