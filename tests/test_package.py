import re
from zipfile import ZipFile

from scripts.package import APPLICATION_CHANGES, TEST_CHANGES, build_archive, build_changes_archives


def test_package_contains_code_but_not_secrets_or_runtime_logs(tmp_path):
    archive_path = build_archive(tmp_path / "project.zip")
    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "practical-example/.env.example" in names
        assert "practical-example/app.py" in names
        assert "practical-example/skills/parse_invoice.ms" in names
        assert "practical-example/docs/architecture.svg" in names
        assert "practical-example/.env" not in names
        assert not any("/tests/" in name or "/testing/" in name or "/docs/demo-" in name for name in names)
        assert not any("/.git/" in name or "/.venv/" in name or "/traces/" in name or name.endswith("/actions.json") for name in names)
        for name in names:
            assert not re.search(rb"sk-[A-Za-z0-9_-]{40,}", archive.read(name))


def test_delta_archives_contain_only_listed_changes_in_separate_packages(tmp_path):
    app, tests = build_changes_archives(tmp_path)
    with ZipFile(app) as archive:
        assert set(archive.namelist()) == {f"practical-example/{name}" for name in APPLICATION_CHANGES}
    with ZipFile(tests) as archive:
        assert set(archive.namelist()) == {f"practical-example/{name}" for name in TEST_CHANGES}
        assert not any("output/" in name or name.endswith("/.env") for name in archive.namelist())
