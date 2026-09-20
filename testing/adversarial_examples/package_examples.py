"""Export this synthetic test run and only the new example files into a ZIP."""
import argparse
import hashlib
import re
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from run_examples import CASES, HERE, ROOT, loads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    run = args.run_directory.resolve()
    rows = loads((run / "results.json").read_text())
    known = {name for name, _, _ in CASES}
    evidence = [Path("results.txt"), Path("results.json"), Path("actions.json")]
    for row in rows:
        if row["file"] not in known:
            raise ValueError("Only the synthetic example fixtures may be exported.")
        relative = Path(row["trace"])
        if relative.parent != Path("traces") or relative.suffix != ".jsonl":
            raise ValueError("Unexpected trace path.")
        events = [loads(line) for line in (run / relative).read_text().splitlines()]
        expected_hash = hashlib.sha256((HERE / "inputs" / row["file"]).read_bytes()).hexdigest()
        if events[0]["data"]["sha256"] != expected_hash:
            raise ValueError("The trace does not belong to the included synthetic fixture.")
        evidence.append(relative)
    observed = HERE / "observed"
    for relative in evidence:
        destination = observed / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run / relative, destination)
    files = [HERE / name for name in ("README.md", "IMAGE_PROMPT.md", "run_examples.py", "package_examples.py", "placeholder-invoice.png")]
    files += [HERE / "inputs" / name for name, _, _ in CASES]
    files += [observed / relative for relative in evidence]
    for path in files:
        if path.is_symlink() or re.search(rb"sk-[A-Za-z0-9_-]{40,}", path.read_bytes()):
            raise ValueError("Unexpected symlink or credential in example package.")
    output = ROOT / "dist/invoice-review-examples.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("practical-example") / path.relative_to(ROOT))
    print(output)


if __name__ == "__main__":
    main()
