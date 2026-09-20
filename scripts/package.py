"""Package application and tests separately; never include .env or user logs."""
import argparse
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
FILES = [".gitignore", ".env.example", "Makefile", "README.md", "ARCHITECTURE.md", "requirements.txt", "app.py"]
PATTERNS = ["invoice_agent/*.py", "scripts/package.py", "schemas/*.json", "skills/*.ms", "samples/*.txt", "samples/*.json", "docs/architecture.svg"]
APPLICATION_CHANGES = [".gitignore", "Makefile", "README.md", "requirements.txt", "invoice_agent/runner.py", "scripts/package.py"]
TEST_CHANGES = ["tests/test_agent.py", "tests/test_package.py", "testing/__init__.py", "testing/llm_judge.py", "testing/test_llm_judge.py", "testing/requirements.txt", "testing/Makefile", "testing/README.md", "testing/reports/saved-trace-judge.txt", "testing/reports/saved-trace-invocation.json"]


def write_archive(destination: Path, sources: set[Path]) -> Path:
    for source in sources:
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Invalid package source: {source.name}")
        # Refuse an accidental real credential; short fake test keys are allowed.
        if re.search(rb"sk-[A-Za-z0-9_-]{40,}", source.read_bytes()):
            raise ValueError(f"Possible API key in package source: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for source in sorted(sources):
            archive.write(source, Path("practical-example") / source.relative_to(ROOT))
    return destination


def build_archive(destination: Path | None = None) -> Path:
    sources = {ROOT / name for name in FILES}
    for pattern in PATTERNS:
        sources.update(ROOT.glob(pattern))
    return write_archive(destination or ROOT / "dist/practical-example.zip", sources)


def build_test_archive(destination: Path | None = None) -> Path:
    sources = {ROOT / name for name in TEST_CHANGES}
    for pattern in ["tests/*.py", "docs/demo-*.jsonl", "docs/demo-results.json", "scripts/demo.py"]:
        sources.update(ROOT.glob(pattern))
    return write_archive(destination or ROOT / "dist/practical-example-testing.zip", sources)


def build_changes_archives(destination: Path | None = None) -> tuple[Path, Path]:
    destination = destination or ROOT / "dist"
    app = write_archive(destination / "practical-example-changes.zip", {ROOT / name for name in APPLICATION_CHANGES})
    tests = write_archive(destination / "practical-example-testing-changes.zip", {ROOT / name for name in TEST_CHANGES})
    return app, tests


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--tests", action="store_true")
    mode.add_argument("--changes", action="store_true")
    args = parser.parse_args()
    if args.changes:
        for archive in build_changes_archives():
            print(archive)
    else:
        print(build_test_archive() if args.tests else build_archive())
