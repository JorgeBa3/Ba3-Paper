"""
benchmark_arrangement.py
────────────────────────
Mide tiempo de ejecución y consistencia del output de yaml_to_midi.py.
Útil para papers de automatización de arreglos musicales.

Usage:
    python benchmark_arrangement.py Prueba1.mid arrangement.yaml
    python benchmark_arrangement.py Prueba1.mid arrangement.yaml --runs 100
    python benchmark_arrangement.py Prueba1.mid arrangement.yaml --runs 1000
"""

import argparse
import hashlib
import io
import os
import statistics
import sys
import time
import warnings
from contextlib import redirect_stdout

# ── Silencia el print interno de yaml_to_midi ────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from yaml_to_midi import apply_arrangement


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run_once(midi_path: str, yaml_path: str, run_id: int) -> tuple[float, str]:
    """
    Ejecuta el pipeline una vez en memoria (sin escribir a disco).
    Devuelve (elapsed_seconds, sha256_del_midi_generado).
    """
    output_path = f"_bench_tmp_{run_id}.mid"

    t0 = time.perf_counter()
    with redirect_stdout(io.StringIO()):          # silencia prints
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            midi_obj = apply_arrangement(midi_path, yaml_path, output_path)
    elapsed = time.perf_counter() - t0

    # Hash del MIDI generado para detectar variaciones de output
    with open(output_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()

    os.remove(output_path)
    return elapsed, digest


def fmt(seconds: float) -> str:
    return f"{seconds * 1000:.2f} ms"


def print_separator(char="─", width=60):
    print(char * width)


# ─────────────────────────────────────────────────────────────────────────────
# Main benchmark
# ─────────────────────────────────────────────────────────────────────────────

def benchmark(midi_path: str, yaml_path: str, runs: int):
    print_separator("═")
    print(f"  BENCHMARK — yaml_to_midi pipeline")
    print(f"  MIDI     : {midi_path}")
    print(f"  YAML     : {yaml_path}")
    print(f"  Runs     : {runs}")
    print_separator("═")

    times   = []
    digests = []

    print(f"\n{'Run':>6}  {'Time':>10}  {'SHA256 (primeros 12)':>14}")
    print_separator()

    for i in range(1, runs + 1):
        elapsed, digest = run_once(midi_path, yaml_path, i)
        times.append(elapsed)
        digests.append(digest)

        # Imprime cada corrida (o cada 100 si son muchas)
        if runs <= 100 or i % 100 == 0 or i == 1:
            print(f"{i:>6}  {fmt(elapsed):>10}  {digest[:12]}")

    # ── Estadísticas de tiempo ────────────────────────────────────────────────
    print_separator()
    print(f"\n{'ESTADÍSTICAS DE TIEMPO':^60}")
    print_separator()
    print(f"  Total runs    : {runs}")
    print(f"  Total time    : {fmt(sum(times))}")
    print(f"  Mean          : {fmt(statistics.mean(times))}")
    print(f"  Median        : {fmt(statistics.median(times))}")
    print(f"  Std dev       : {fmt(statistics.stdev(times)) if runs > 1 else 'N/A'}")
    print(f"  Min           : {fmt(min(times))}")
    print(f"  Max           : {fmt(max(times))}")
    print(f"  p95           : {fmt(sorted(times)[int(runs * 0.95)])}")
    print(f"  p99           : {fmt(sorted(times)[int(runs * 0.99)])}")

    # ── Análisis de consistencia del output ──────────────────────────────────
    unique_digests = set(digests)
    print_separator()
    print(f"\n{'CONSISTENCIA DEL OUTPUT':^60}")
    print_separator()
    print(f"  Outputs únicos  : {len(unique_digests)} / {runs}")

    if len(unique_digests) == 1:
        print(f"  Resultado       : ✅ DETERMINISTA — output idéntico en todas las corridas")
        print(f"  SHA256          : {list(unique_digests)[0]}")
    else:
        print(f"  Resultado       : ⚠️  NO-DETERMINISTA — el output varía entre corridas")
        print(f"  (esperado si usás la transformación 'humanize')")
        print(f"\n  Hashes únicos encontrados:")
        for d in sorted(unique_digests):
            count = digests.count(d)
            print(f"    {d[:16]}...  ×{count} veces ({count/runs*100:.1f}%)")

    print_separator("═")
    print(f"  ✅ Benchmark completo")
    print_separator("═")

    # ── CSV para el paper ─────────────────────────────────────────────────────
    csv_path = f"benchmark_{runs}runs.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("run,time_ms,sha256\n")
        for i, (t, d) in enumerate(zip(times, digests), 1):
            f.write(f"{i},{t*1000:.4f},{d}\n")
    print(f"\n  📄 CSV guardado → {csv_path}")
    print_separator("═")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark de tiempo y consistencia del pipeline yaml_to_midi."
    )
    parser.add_argument("midi_file", help="Archivo .mid original")
    parser.add_argument("yaml_file", help="Archivo .yaml de arreglo")
    parser.add_argument(
        "--runs", "-n", type=int, default=100,
        help="Número de ejecuciones (default: 100)"
    )
    args = parser.parse_args()
    benchmark(args.midi_file, args.yaml_file, args.runs)


if __name__ == "__main__":
    main()