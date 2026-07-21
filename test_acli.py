#!/usr/bin/env python3
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from acli import copy_with_cow_rsync_fallback, get_ignored_paths


class TestGitignoreSafeguard(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.p_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_no_gitignore(self):
        (self.p_path / "hello.py").touch()
        ignored = get_ignored_paths(self.p_path)
        self.assertEqual(ignored, [])

    def test_ignored_files_and_directories(self):
        (self.p_path / ".gitignore").write_text("build/\n*.log\n.venv\n")
        (self.p_path / "build").mkdir()
        (self.p_path / "build" / "output.o").touch()
        (self.p_path / "app.log").touch()
        (self.p_path / ".venv").mkdir()
        (self.p_path / ".venv" / "bin").mkdir()
        (self.p_path / ".venv" / "bin" / "python").touch()
        (self.p_path / "src").mkdir()
        (self.p_path / "src" / "main.py").touch()

        ignored = get_ignored_paths(self.p_path)
        rel_strings = [str(p) for p in ignored]

        self.assertIn("app.log", rel_strings)
        self.assertIn("build", rel_strings)
        self.assertIn(".venv", rel_strings)
        self.assertNotIn("src/main.py", rel_strings)
        # Verify parent pruning: subfile build/output.o should not be listed if build is listed
        self.assertNotIn("build/output.o", rel_strings)

    def test_git_folder_excluded(self):
        (self.p_path / ".gitignore").write_text("*\n")
        dot_git = self.p_path / ".git"
        dot_git.mkdir()
        (dot_git / "config").touch()
        (dot_git / "hooks").mkdir()
        (dot_git / "hooks" / "pre-commit").touch()

        ignored = get_ignored_paths(self.p_path)
        rel_strings = [str(p) for p in ignored]

        self.assertNotIn(".git", rel_strings)
        self.assertNotIn(".git/config", rel_strings)
        self.assertNotIn(".git/hooks", rel_strings)

    def test_copy_fallback(self):
        src_dir = self.p_path / "src_build"
        src_dir.mkdir()
        (src_dir / "file1.txt").write_text("data1")
        dst_dir = self.p_path / "dst_build"

        copy_with_cow_rsync_fallback(src_dir, dst_dir)
        self.assertTrue((dst_dir / "file1.txt").exists())
        self.assertEqual((dst_dir / "file1.txt").read_text(), "data1")


if __name__ == "__main__":
    unittest.main()

