"""
Get the shop data: clone a tagged release of Data-Generator, run it (seed 42) and copy the tables the engine reads
to data/raw/, together with the true price elasticity from its settings.

    python scripts/get_data.py                      # the release in pricing_engine.data.DATA_GENERATOR_TAG
    python scripts/get_data.py --tag v1.4.3         # another release
    python scripts/get_data.py --source ../Data-Generator   # a local clone instead of GitHub
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pricing_engine.data import DATA_GENERATOR_TAG, RAW_DIR, TABLES  # noqa: E402

GITHUB_URL = "https://github.com/tlabedzki/Data-Generator.git"
CACHE_DIR = ROOT / ".cache"

TRUTH_SCRIPT = """
import json
from settings import commerce_settings as cs
print(json.dumps({
    "category_price_elasticity": cs.category_price_elasticity,
    "default_price_elasticity": cs.default_price_elasticity,
}))
"""


def run(command: list[str], cwd: Path | None = None) -> str:
    env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"Command failed: {' '.join(command)}\n{result.stderr[-2000:]}")
    return result.stdout


def clone(source: str, tag: str) -> Path:
    target = CACHE_DIR / f"data-generator-{tag}"
    if not (target / "main.py").exists():
        shutil.rmtree(target, ignore_errors=True)
        CACHE_DIR.mkdir(exist_ok=True)
        print(f"Cloning Data-Generator {tag} from {source}")
        run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", tag,
             source, str(target)])
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", default=DATA_GENERATOR_TAG, help="Data-Generator release tag")
    parser.add_argument("--source", default=GITHUB_URL, help="git URL or local path of Data-Generator")
    args = parser.parse_args()

    generator_dir = clone(args.source, args.tag)
    export_dir = generator_dir / "export"
    if not (export_dir / "product_data.parquet").exists():
        print("Generating the data (seed 42), about 10 seconds")
        run([sys.executable, "main.py"], cwd=generator_dir)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    for table in TABLES:
        source_file = export_dir / f"{table}.parquet"
        if source_file.exists():
            shutil.copy2(source_file, RAW_DIR / source_file.name)
            copied.append(table)
    stale = RAW_DIR / "competitor_prices.parquet"
    if "competitor_prices" not in copied and stale.exists():
        stale.unlink()

    truth = json.loads(run([sys.executable, "-c", TRUTH_SCRIPT], cwd=generator_dir))
    commit = run(["git", "rev-parse", "HEAD"], cwd=generator_dir).strip()
    truth["source"] = {"repository": GITHUB_URL, "tag": args.tag, "commit": commit, "seed": 42}
    (RAW_DIR / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")

    print(f"Saved {', '.join(copied)} and truth.json to {RAW_DIR.relative_to(ROOT)}")
    if "competitor_prices" not in copied:
        print("This release has no competitor_prices table: the engine uses the mock table instead.")


if __name__ == "__main__":
    main()
