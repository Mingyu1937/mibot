"""
Benchmark a bot against sparring partners in duplicate pairs (same seed, seats swapped).

Default opponents: bots/caller plus every .py file in my_bots/sparringbots/.
Score per pair: 1 = won both matches, 0.5 = split, 0 = lost both.
"""

import glob
import math
import os
import random
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

LINE = re.compile(
    r"^\s*(\d)\.\s+(\S+)\s+([\d,]+)\s+\(([+-][\d,]+)\)\s+avg think (\d+) ms(?:\s+(\d+) errors)?",
    re.MULTILINE,
)


def display_name(path: str) -> str:
    """The name play.py prints for a bot: folder name, or file name without .py."""
    name = os.path.basename(path.rstrip("/"))
    return name[:-3] if name.endswith(".py") else name


def play_single(bot_a: str, bot_b: str, seed: int, hero_name: str):
    """One match. Returns (hero_won, hero_errors, hero_avg_think_ms, ok)."""
    cmd = [sys.executable, "play.py", bot_a, bot_b, "--seed", str(seed)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    rows = {m.group(2): m for m in LINE.finditer(proc.stdout)}
    if hero_name not in rows:
        return False, 0, 0, False                        # play.py printed no result: match didn't run
    # Note: play.py exits with code 1 when a bot had errors, so we read the error count from its output.
    row = rows[hero_name]
    return row.group(1) == "1", int(row.group(6) or 0), int(row.group(5)), True


def play_pair(args):
    """Both seat orders with the same seed. Returns (pair_score, errors, max_think_ms, bad_matches)."""
    hero, villain, seed, hero_name = args
    w1, e1, t1, ok1 = play_single(hero, villain, seed, hero_name)
    w2, e2, t2, ok2 = play_single(villain, hero, seed, hero_name)
    return (int(w1) + int(w2)) / 2, e1 + e2, max(t1, t2), int(not ok1) + int(not ok2)


def benchmark(hero: str, villain: str, pairs: int, bench_seed: int = None):
    hero_name = display_name(hero)
    if hero_name == display_name(villain):
        sys.exit(f"Both bots are called '{hero_name}'. Rename one so results can be told apart.")

    if bench_seed is None:
        bench_seed = random.SystemRandom().randint(1, 10_000_000)

    rng = random.Random(bench_seed)            # same seeds for every opponent and every bot version
    tasks = [(hero, villain, rng.randint(1, 10_000_000), hero_name) for _ in range(pairs)]

    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as pool:
        results = list(pool.map(play_pair, tasks))
    elapsed = time.perf_counter() - t0

    scores = [r[0] for r in results]
    errors = sum(r[1] for r in results)
    slowest = max(r[2] for r in results)
    bad = sum(r[3] for r in results)

    mean = statistics.mean(scores)
    margin = 1.96 * statistics.pstdev(scores) / math.sqrt(len(scores)) if len(scores) > 1 else 0
    w = sum(s == 1 for s in scores)
    d = sum(s == 0.5 for s in scores)
    l = sum(s == 0 for s in scores)
    print(
        f"vs {display_name(villain):<12} | seed: {bench_seed} | {pairs} pairs | W:{w} D:{d} L:{l} | "
        f"Score: {mean * 100:5.1f}% +-{margin * 100:4.1f} | bot errors: {errors} | "
        f"slowest avg think: {slowest} ms | failed matches: {bad} | {elapsed:.0f}s"
    )
    return mean


if __name__ == "__main__":
    hero = sys.argv[1] if len(sys.argv) > 1 else "my_bots/mibot"
    pairs = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    opponents = sys.argv[3:] or ["bots/caller"] + sorted(glob.glob("my_bots/sparringbots/*.py"))

    means = [benchmark(hero, opp, pairs) for opp in opponents]
    print(f"Average over {len(means)} opponents: {statistics.mean(means) * 100:.1f}%")
