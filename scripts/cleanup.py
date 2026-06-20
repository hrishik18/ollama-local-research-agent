"""Disk rotation for repeated overnight runs.

Keeps only the last N iterations, prunes cache entries older than --max-age-days,
and optionally removes downloaded PDFs older than --pdf-age-days. Always dry-runs
first; pass --apply to actually delete.

Usage:
    python scripts/cleanup.py                       # dry run, default policy
    python scripts/cleanup.py --apply
    python scripts/cleanup.py --keep-last 5 --max-age-days 7 --pdf-age-days 14 --apply

What it touches:
    history/iteration_*/        keep last --keep-last (default 10)
    cache/                      delete files older than --max-age-days (default 14)
    state/pdfs/                 delete files older than --pdf-age-days (default 30)
    outputs/*.jsonl             rotates files > 50 MB by truncating to last 20 MB

Always leaves:
    history/experiment_*.md     (free-form notes, never auto-deleted)
    history/benchmark_report.json
    prompt.md, plan.md, configs
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _size_mb(p: Path) -> float:
    try:
        if p.is_file():
            return p.stat().st_size / (1024 * 1024)
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / (1024 * 1024)
    except OSError:
        return 0.0


def prune_iterations(history: Path, keep_last: int, apply: bool) -> tuple[int, float]:
    if not history.exists():
        return 0, 0.0
    iters = sorted([d for d in history.glob("iteration_*") if d.is_dir()], key=lambda p: p.name)
    to_remove = iters[:-keep_last] if len(iters) > keep_last else []
    freed = 0.0
    for d in to_remove:
        size = _size_mb(d)
        freed += size
        print(f"  - iter {d.name:<18} ({size:.2f} MB)")
        if apply:
            shutil.rmtree(d, ignore_errors=True)
    return len(to_remove), freed


def prune_old_files(directory: Path, max_age_days: float, apply: bool, label: str) -> tuple[int, float]:
    if not directory.exists():
        return 0, 0.0
    cutoff = time.time() - max_age_days * 86400
    n, freed = 0, 0.0
    for f in directory.rglob("*"):
        if not f.is_file():
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            size = f.stat().st_size / (1024 * 1024)
            n += 1
            freed += size
            if apply:
                try:
                    f.unlink()
                except OSError as e:
                    print(f"    ! could not delete {f}: {e}")
    print(f"  - {label}: {n} files, {freed:.2f} MB" + (" (deleted)" if apply else " (would delete)"))
    return n, freed


def truncate_large_logs(outputs: Path, max_size_mb: float, keep_tail_mb: float, apply: bool) -> int:
    if not outputs.exists():
        return 0
    n = 0
    for f in outputs.glob("*.jsonl"):
        size_mb = _size_mb(f)
        if size_mb > max_size_mb:
            print(f"  - log {f.name}: {size_mb:.1f} MB -> truncate to last {keep_tail_mb:.0f} MB")
            n += 1
            if apply:
                data = f.read_bytes()
                keep = int(keep_tail_mb * 1024 * 1024)
                tail = data[-keep:] if len(data) > keep else data
                # Drop possibly-incomplete first line
                nl = tail.find(b"\n")
                if nl != -1:
                    tail = tail[nl + 1:]
                f.write_bytes(tail)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--keep-last", type=int, default=10, help="iterations to retain")
    ap.add_argument("--max-age-days", type=float, default=14.0, help="cache TTL in days")
    ap.add_argument("--pdf-age-days", type=float, default=30.0, help="downloaded-PDF TTL in days")
    ap.add_argument("--max-log-mb", type=float, default=50.0, help="rotate JSONL above this size")
    ap.add_argument("--keep-log-tail-mb", type=float, default=20.0, help="MB to keep when rotating")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args()

    root = Path(args.root)
    print(f"{'APPLYING' if args.apply else 'DRY RUN'} cleanup under {root}")
    print()

    print(f"history/iteration_*  (keep last {args.keep_last}):")
    n_iter, freed_iter = prune_iterations(root / "history", args.keep_last, args.apply)

    print(f"cache/  (older than {args.max_age_days} days):")
    n_cache, freed_cache = prune_old_files(root / "cache", args.max_age_days, args.apply, "cache files")

    print(f"state/pdfs/  (older than {args.pdf_age_days} days):")
    n_pdf, freed_pdf = prune_old_files(root / "state" / "pdfs", args.pdf_age_days, args.apply, "PDFs")

    print(f"outputs/*.jsonl  (rotate above {args.max_log_mb} MB):")
    n_log = truncate_large_logs(root / "outputs", args.max_log_mb, args.keep_log_tail_mb, args.apply)

    total_freed = freed_iter + freed_cache + freed_pdf
    print()
    print(f"Summary: {n_iter} iters, {n_cache} cache files, {n_pdf} PDFs, {n_log} logs "
          f"-> {total_freed:.2f} MB" + (" freed" if args.apply else " would be freed"))
    if not args.apply:
        print("\n(re-run with --apply to actually delete)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
