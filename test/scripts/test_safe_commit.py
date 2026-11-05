"""フックの書き換えで再試行するとき、ステージしていない他の変更を巻き込まない。

作業ツリーには別セッションの未コミット変更がある(CLAUDE.md)。
再試行で `git add -u` すると、それらが全部コミットに入ってしまっていた。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import safe_commit  # noqa: E402


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True)
    return result.stdout


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    (repo / "mine.txt").write_text("old\n", encoding="utf-8")
    (repo / "others.txt").write_text("old\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    # 整形フックの真似: mine.txt が未整形ならファイルを書き換えて失敗する。整形済みなら通す
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\nif ! grep -q formatted mine.txt; then\n  echo formatted >> mine.txt\n  exit 1\nfi\n",
        encoding="utf-8",
        newline="\n",
    )
    hook.chmod(0o755)
    return repo


def test_retry_restages_only_what_was_staged(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    (repo / "mine.txt").write_text("new\n", encoding="utf-8")
    (repo / "others.txt").write_text("別セッションの編集\n", encoding="utf-8")
    git(repo, "add", "mine.txt")
    monkeypatch.chdir(repo)

    assert safe_commit.main(["test: 再試行"]) == 0

    committed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["mine.txt"]
    assert "formatted" in git(repo, "show", "HEAD:mine.txt")
    # 他の変更は未ステージのまま残る
    assert git(repo, "status", "--porcelain").splitlines() == [" M others.txt"]


def test_commit_without_hook_rewrite_is_plain(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    (repo / "mine.txt").write_text("formatted\n", encoding="utf-8")
    git(repo, "add", "mine.txt")
    monkeypatch.chdir(repo)
    assert safe_commit.main(["test: 通常"]) == 0
    assert git(repo, "status", "--porcelain") == ""
