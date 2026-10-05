"""pull-restart.ps1 must not feed CRLF sleep args to bash over ssh."""

from pathlib import Path


def test_pull_restart_sends_remote_script_via_base64():
    text = Path("pull-restart.ps1").read_text(encoding="utf-8")
    assert "echo $b64 | base64 -d | bash -s" in text
    # Must not pipe the here-string directly (re-CRLF on Windows).
    assert "$remote | ssh" not in text
