from scripts import manage_archive_backup


def test_backup_cli_create_command(monkeypatch, capsys):
    calls = {}

    class FakeBackup:
        def __init__(self, base_directory):
            calls["base_directory"] = base_directory

        def create_backup(self, output):
            calls["output"] = output
            return {"backup_path": output, "file_count": 2}

    monkeypatch.setattr(manage_archive_backup, "ArchiveBackup", FakeBackup)
    monkeypatch.setattr(
        "sys.argv",
        [
            "manage_archive_backup.py",
            "--base-directory", "/archive",
            "create",
            "--output", "/backups/snapshot.zip",
        ],
    )

    assert manage_archive_backup.main() == 0
    assert calls == {
        "base_directory": "/archive",
        "output": "/backups/snapshot.zip",
    }
    assert '"file_count": 2' in capsys.readouterr().out


def test_backup_cli_returns_nonzero_for_invalid_operation(monkeypatch, capsys):
    class FailingBackup:
        def __init__(self, base_directory):
            pass

        def verify_backup(self, backup):
            raise ValueError("invalid archive")

    monkeypatch.setattr(manage_archive_backup, "ArchiveBackup", FailingBackup)
    monkeypatch.setattr(
        "sys.argv",
        ["manage_archive_backup.py", "verify", "--backup", "bad.zip"],
    )

    assert manage_archive_backup.main() == 1
    assert "invalid archive" in capsys.readouterr().err
