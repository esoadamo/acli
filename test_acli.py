#!/usr/bin/env python3
import os
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from acli import copy_with_cow_rsync_fallback, get_ignored_paths, main


class TestCopyWithCowRsyncFallback(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.p_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("acli.subprocess.run")
    def test_reflink_success(self, mock_run):
        mock_run.return_value.returncode = 0
        src = self.p_path / "src.txt"
        dst = self.p_path / "dst.txt"
        src.touch()
        copy_with_cow_rsync_fallback(src, dst)
        mock_run.assert_called_once_with(
            ["cp", "--reflink=always", "-a", str(src), str(dst)],
            capture_output=True,
            text=True,
        )

    @patch("acli.subprocess.run")
    def test_reflink_fails_rsync_success_file(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=0),
        ]
        src = self.p_path / "src.txt"
        dst = self.p_path / "dst.txt"
        src.touch()
        copy_with_cow_rsync_fallback(src, dst)
        self.assertEqual(mock_run.call_count, 2)

    @patch("acli.subprocess.run")
    def test_reflink_fails_rsync_success_dir(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=0),
        ]
        src = self.p_path / "src_dir"
        dst = self.p_path / "dst_dir"
        src.mkdir()
        copy_with_cow_rsync_fallback(src, dst)
        self.assertEqual(mock_run.call_count, 2)

    @patch("acli.subprocess.run")
    def test_reflink_exception_rsync_exception_fallback_new_file(self, mock_run):
        mock_run.side_effect = Exception("Command failed")
        src = self.p_path / "src.txt"
        dst = self.p_path / "dst.txt"
        src.write_text("hello")
        copy_with_cow_rsync_fallback(src, dst)
        self.assertTrue(dst.exists())
        self.assertEqual(dst.read_text(), "hello")

    @patch("acli.subprocess.run")
    def test_reflink_fails_rsync_fails_fallback_new_dir(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=1),
        ]
        src = self.p_path / "src_dir"
        dst = self.p_path / "dst_dir"
        src.mkdir()
        (src / "sub.txt").write_text("content")
        copy_with_cow_rsync_fallback(src, dst)
        self.assertTrue((dst / "sub.txt").exists())

    @patch("acli.subprocess.run")
    def test_reflink_fails_rsync_fails_fallback_copytree(self, mock_run):
        src = self.p_path / "src_dir"
        dst = self.p_path / "dst_dir"
        src.mkdir()
        (src / "sub.txt").write_text("content")

        def side_effect(*args, **kwargs):
            if dst.exists():
                shutil.rmtree(dst)
            return MagicMock(returncode=1)

        mock_run.side_effect = side_effect
        copy_with_cow_rsync_fallback(src, dst)
        self.assertTrue((dst / "sub.txt").exists())

    @patch("acli.subprocess.run")
    def test_reflink_fails_rsync_fails_fallback_existing_dir(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=1),
        ]
        src = self.p_path / "src_dir"
        dst = self.p_path / "dst_dir"
        src.mkdir()
        dst.mkdir()

        f_new = src / "new.txt"
        f_new.write_text("new")
        
        f_newer = src / "newer.txt"
        f_newer.write_text("newer_src")
        
        f_older = src / "older.txt"
        f_older.write_text("older_src")

        d_newer = dst / "newer.txt"
        d_newer.write_text("newer_dst")

        d_older = dst / "older.txt"
        d_older.write_text("older_dst")

        os.utime(f_newer, (2000, 2000))
        os.utime(d_newer, (1000, 1000))

        os.utime(f_older, (1000, 1000))
        os.utime(d_older, (2000, 2000))

        copy_with_cow_rsync_fallback(src, dst)

        self.assertEqual((dst / "new.txt").read_text(), "new")
        self.assertEqual((dst / "newer.txt").read_text(), "newer_src")
        self.assertEqual((dst / "older.txt").read_text(), "older_dst")

    @patch("acli.subprocess.run")
    def test_reflink_fails_rsync_fails_fallback_existing_file(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=1),
        ]
        src1 = self.p_path / "src1.txt"
        dst1 = self.p_path / "dst1.txt"
        src1.write_text("src1_new")
        dst1.write_text("dst1_old")
        os.utime(src1, (2000, 2000))
        os.utime(dst1, (1000, 1000))

        copy_with_cow_rsync_fallback(src1, dst1)
        self.assertEqual(dst1.read_text(), "src1_new")

        src2 = self.p_path / "src2.txt"
        dst2 = self.p_path / "dst2.txt"
        src2.write_text("src2_old")
        dst2.write_text("dst2_new")
        os.utime(src2, (1000, 1000))
        os.utime(dst2, (2000, 2000))

        copy_with_cow_rsync_fallback(src2, dst2)
        self.assertEqual(dst2.read_text(), "dst2_new")


class TestGetIgnoredPaths(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.p_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_no_gitignore(self):
        (self.p_path / "hello.py").touch()
        ignored = get_ignored_paths(self.p_path)
        self.assertEqual(ignored, [])

    @patch("acli.subprocess.run")
    def test_git_ls_files_success(self, mock_run):
        (self.p_path / ".gitignore").write_text("*.log\n")
        (self.p_path / "app.log").touch()
        (self.p_path / "build").mkdir()
        (self.p_path / "build" / "out.o").touch()

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="app.log\nbuild/\nbuild/out.o\n\n"
        )
        ignored = get_ignored_paths(self.p_path)
        rel_strings = [str(p) for p in ignored]
        self.assertIn("app.log", rel_strings)
        self.assertIn("build", rel_strings)
        # Parent pruning test (lines 699-700)
        self.assertNotIn("build/out.o", rel_strings)

    @patch("acli.subprocess.run")
    def test_git_ls_files_exception_fallback(self, mock_run):
        mock_run.side_effect = Exception("git error")
        (self.p_path / ".gitignore").write_text("*.log\n")
        (self.p_path / "app.log").touch()

        ignored = get_ignored_paths(self.p_path)
        rel_strings = [str(p) for p in ignored]
        self.assertIn("app.log", rel_strings)

    @patch("acli.subprocess.run")
    def test_git_ls_files_nonzero_fallback(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        (self.p_path / ".gitignore").write_text("*.log\n")
        (self.p_path / "app.log").touch()

        ignored = get_ignored_paths(self.p_path)
        rel_strings = [str(p) for p in ignored]
        self.assertIn("app.log", rel_strings)

    @patch("acli.subprocess.run")
    def test_gitignore_read_text_exception(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        gi_file = self.p_path / ".gitignore"
        gi_file.touch()

        with patch.object(Path, "read_text", side_effect=Exception("Read error")):
            ignored = get_ignored_paths(self.p_path)
            self.assertEqual(ignored, [])

    @patch("acli.subprocess.run")
    def test_gitignore_empty_and_comments(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        (self.p_path / ".gitignore").write_text("# Only a comment\n\n   \n")
        (self.p_path / "file.txt").touch()

        ignored = get_ignored_paths(self.p_path)
        self.assertEqual(ignored, [])

    @patch("acli.subprocess.run")
    def test_gitignore_pattern_matching(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        gitignore_content = """
# Comments
build/
*.log
!important.log
dir/sub/
/root_only.txt
"""
        (self.p_path / ".gitignore").write_text(gitignore_content)
        (self.p_path / "build").mkdir()
        (self.p_path / "build" / "out.o").touch()
        (self.p_path / "test.log").touch()
        (self.p_path / "important.log").touch()

        dot_git = self.p_path / ".git"
        dot_git.mkdir()
        (dot_git / "HEAD").touch()
        
        dir_sub = self.p_path / "dir" / "sub"
        dir_sub.mkdir(parents=True)
        (dir_sub / "data.txt").touch()

        (self.p_path / "root_only.txt").touch()

        ignored = get_ignored_paths(self.p_path)
        rel_strings = [str(p) for p in ignored]

        self.assertIn("build", rel_strings)
        self.assertIn("test.log", rel_strings)
        self.assertNotIn("important.log", rel_strings)
        self.assertIn("dir/sub", rel_strings)
        self.assertIn("root_only.txt", rel_strings)
        self.assertNotIn("build/out.o", rel_strings)

    @patch("acli.subprocess.run")
    def test_gitignore_relative_to_value_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        (self.p_path / ".gitignore").write_text("*.txt\n")

        fail_file = self.p_path / "fail_rel.txt"
        fail_file.touch()

        orig_rel = Path.relative_to
        def mock_rel(self_obj, other):
            if "fail_rel" in str(self_obj):
                raise ValueError("Relative to error")
            return orig_rel(self_obj, other)

        with patch.object(Path, "relative_to", autospec=True, side_effect=mock_rel):
            ignored = get_ignored_paths(self.p_path)
            rel_strings = [str(p) for p in ignored]
            self.assertNotIn("fail_rel.txt", rel_strings)

    @patch("acli.subprocess.run")
    def test_git_folder_and_nonexistent_paths_pruned(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=".git/config\ngit_dir/file\nnonexistent.txt\nvalid.txt\n"
        )
        (self.p_path / ".gitignore").write_text("dummy\n")
        (self.p_path / "valid.txt").touch()

        ignored = get_ignored_paths(self.p_path)
        rel_strings = [str(p) for p in ignored]
        self.assertEqual(rel_strings, ["valid.txt"])


class TestMainFunction(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.p_path = Path(self.test_dir)
        self.userns_patcher = patch("acli.check_userns_supported", return_value=True)
        self.mock_userns_supported = self.userns_patcher.start()

    def tearDown(self):
        self.userns_patcher.stop()
        for root, dirs, files in os.walk(self.test_dir):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o777)
            for f in files:
                os.chmod(os.path.join(root, f), 0o666)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_main_nonexistent_project_dir(self):
        non_existent = str(self.p_path / "no_dir")
        with patch("sys.argv", ["acli", non_existent]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)

    @patch("acli.subprocess.run")
    @patch("acli.subprocess.Popen")
    def test_main_agcli_base_missing_creation_failure(self, mock_popen, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout="REPOSITORY TAG IMAGE ID CREATED SIZE\n"),
            MagicMock(returncode=0),
        ]
        proc_mock = MagicMock()
        proc_mock.communicate.return_value = (b"", b"")
        proc_mock.returncode = 2
        mock_popen.return_value = proc_mock

        with patch("sys.argv", ["acli", str(self.p_path)]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 2)

    @patch("acli.subprocess.run")
    @patch("acli.subprocess.Popen")
    def test_main_agcli_base_missing_creation_success(self, mock_popen, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout="REPOSITORY TAG IMAGE ID CREATED SIZE\n"),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        proc_mock = MagicMock()
        proc_mock.communicate.return_value = (b"", b"")
        proc_mock.returncode = 0
        mock_popen.return_value = proc_mock

        fake_home = self.p_path / "fake_home"
        fake_home.mkdir()

        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("sys.argv", ["acli", str(self.p_path)]):
                with patch("sys.exit") as mock_exit:
                    main()
                    mock_exit.assert_called_once_with(0)

    @patch("acli.subprocess.run")
    def test_main_full_options_and_tool_mounts(self, mock_run):
        def subprocess_run_side_effect(cmd, *args, **kwargs):
            if "podman" in cmd and "images" in cmd:
                return MagicMock(stdout="REPOSITORY TAG IMAGE ID CREATED SIZE\nagcli-base latest 12345 2 hours ago 1GB\n", returncode=0)
            elif "git" in cmd and "ls-files" in cmd:
                return MagicMock(stdout="ignored.txt\n", returncode=0)
            return MagicMock(stdout="", returncode=0)

        mock_run.side_effect = subprocess_run_side_effect

        fake_home = self.p_path / "fake_home"
        copilot_dir = fake_home / ".copilot"
        vibe_dir = fake_home / ".vibe"
        ag_dir = fake_home / ".gemini" / "antigravity-cli"

        copilot_dir.mkdir(parents=True)
        vibe_dir.mkdir(parents=True)
        ag_dir.mkdir(parents=True)

        (copilot_dir / "command-history-state.json").write_text("{}")
        (copilot_dir / "session-store.db").touch()
        (vibe_dir / "vibehistory").write_text("hist")
        (ag_dir / "history.jsonl").write_text("{}")
        (ag_dir / "conversation_summaries.db").touch()

        symlink_file = ag_dir / "cli.log"
        target_log = ag_dir / "cli_target.log"
        target_log.touch()
        symlink_file.symlink_to(target_log)

        claude_dir = fake_home / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "history.jsonl").write_text("{}")
        (claude_dir / "settings.json").write_text("{}")
        (claude_dir / ".credentials.json").write_text('{"token": "test"}')
        claude_json = fake_home / ".claude.json"
        claude_json.write_text('{"oauth": "token"}')

        (self.p_path / ".gitignore").write_text("ignored.txt\n")
        (self.p_path / "ignored.txt").touch()

        root_git = self.p_path / ".git"
        root_git.mkdir()
        (root_git / "hooks").mkdir()
        (root_git / "config").touch()

        sub_git_dir = self.p_path / "sub_repo" / ".git"
        sub_git_dir.mkdir(parents=True)
        (sub_git_dir / "hooks").mkdir()

        sub_git_file = self.p_path / "sub_worktree" / ".git"
        sub_git_file.parent.mkdir(parents=True)
        gitdir_target = self.p_path / "gitdir_target"
        gitdir_target.mkdir()
        (gitdir_target / "hooks").mkdir()
        (gitdir_target / "config").touch()
        sub_git_file.write_text(f"gitdir: {gitdir_target}")

        rel_gitdir_file = self.p_path / "rel_worktree" / ".git"
        rel_gitdir_file.parent.mkdir(parents=True)
        rel_target = self.p_path / "rel_worktree" / "gitdir_rel"
        rel_target.mkdir()
        (rel_target / "config").touch()
        rel_gitdir_file.write_text("gitdir: gitdir_rel")

        invalid_gitdir_file = self.p_path / "invalid_worktree" / ".git"
        invalid_gitdir_file.parent.mkdir(parents=True)
        invalid_gitdir_file.write_text("gitdir: /nonexistent/path")

        bad_gitdir_file = self.p_path / "bad_worktree" / ".git"
        bad_gitdir_file.parent.mkdir(parents=True)
        bad_gitdir_file.write_text("gitdir: something")
        os.chmod(bad_gitdir_file, 0o000)

        # User git configs
        (fake_home / ".gitconfig").touch()
        git_cfg_dir = fake_home / ".config" / "git"
        git_cfg_dir.mkdir(parents=True)
        (git_cfg_dir / "config").touch()

        # Workspace protection targets
        (self.p_path / ".envrc").touch()
        vscode_dir = self.p_path / ".vscode"
        vscode_dir.mkdir()
        (vscode_dir / "tasks.json").touch()
        (vscode_dir / "launch.json").touch()
        (vscode_dir / "settings.json").touch()
        (self.p_path / ".idea").mkdir()

        # Mask env targets
        (self.p_path / ".env").touch()
        (self.p_path / ".env.local").touch()
        (self.p_path / ".env.acli").touch()

        # Pre-create per-project claude storage so the "already exists" branches are covered
        project_slug = str(self.p_path.resolve()).replace("/", "_").lstrip("_")
        claude_proj_storage = fake_home / ".acli" / "projects" / project_slug / "claude"
        claude_proj_config = claude_proj_storage / "config"
        claude_proj_config.mkdir(parents=True, exist_ok=True)
        (claude_proj_config / "settings.json").write_text("{}")
        (claude_proj_storage / ".claude.json").write_text('{"oauth": "cached"}')

        # Test case 1: git-mode=ro, git-hooks-mode=tmpfs, persistence=per-project, tools-ro=true
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("sys.argv", [
                "acli", str(self.p_path),
                "--git-mode", "ro",
                "--git-hooks-mode", "tmpfs",
                "--gitignore-mode", "mask",
                "--persistence", "per-project",
                "--tools-ro",
                "--workspace-protection",
                "--mask-env",
                "--memory", "8G",
            ]):
                with patch("sys.exit") as mock_exit:
                    main()
                    mock_exit.assert_called_once_with(0)

        # Test case 2: git-mode=rw, git-hooks-mode=ro, persistence=global, tools-ro=true
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("sys.argv", [
                "acli", str(self.p_path),
                "--git-mode", "rw",
                "--git-hooks-mode", "ro",
                "--gitignore-mode", "ro",
                "--persistence", "global",
                "--tools-ro",
                "--no-workspace-protection",
                "--no-mask-env",
            ]):
                with patch("sys.exit") as mock_exit:
                    main()
                    mock_exit.assert_called_once_with(0)

        # Test case 3: git-mode=rw, git-hooks-mode=tmpfs, gitignore-mode=rw, tools-ro=false
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("sys.argv", [
                "acli", str(self.p_path),
                "--git-mode", "rw",
                "--git-hooks-mode", "tmpfs",
                "--gitignore-mode", "rw",
                "--no-tools-ro",
            ]):
                with patch("sys.exit") as mock_exit:
                    main()
                    mock_exit.assert_called_once_with(0)

    @patch("acli.subprocess.run")
    def test_main_env_var_defaults_and_write_bytes_exception(self, mock_run):
        mock_run.return_value = MagicMock(stdout="agcli-base latest\nheader line\n", returncode=0)

        fake_home = self.p_path / "fake_home"
        copilot_dir = fake_home / ".copilot"
        vibe_dir = fake_home / ".vibe"
        ag_dir = fake_home / ".gemini" / "antigravity-cli"
        copilot_dir.mkdir(parents=True)
        vibe_dir.mkdir(parents=True)
        ag_dir.mkdir(parents=True)

        (copilot_dir / "command-history-state.json").write_text("{}")
        (copilot_dir / "session-store.db").touch()
        (vibe_dir / "vibehistory").write_text("hist")
        (ag_dir / "history.jsonl").write_text("{}")
        (ag_dir / "conversation_summaries.db").touch()

        claude_dir = fake_home / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "history.jsonl").write_text("{}")
        claude_json = fake_home / ".claude.json"
        claude_json.write_text('{"oauth": "token"}')

        env_override = {
            "ACLI_MEMORY": "32G",
            "ACLI_TOOLS": "copilot,vibe,antigravity,claude",
            "ACLI_PERSISTENCE": "invalid_persistence_value",
            "ACLI_TOOLS_RO": "1",
            "ACLI_GIT_MODE": "",
            "ACLI_GIT_PROTECTION": "false",
            "ACLI_GIT_HOOKS_MODE": "",
            "ACLI_GITIGNORE_MODE": "invalid_mode",
            "ACLI_WORKSPACE_PROTECTION": "off",
            "ACLI_MASK_ENV": "0",
        }

        original_write_bytes = Path.write_bytes
        def mock_write_bytes(path_obj, data):
            if "proj_storage_root" in str(path_obj) or ".acli" in str(path_obj):
                raise PermissionError("Permission denied")
            return original_write_bytes(path_obj, data)

        with patch("pathlib.Path.home", return_value=fake_home):
            with patch.dict(os.environ, env_override):
                with patch("sys.argv", ["acli", str(self.p_path)]):
                    with patch.object(Path, "write_bytes", side_effect=mock_write_bytes):
                        with patch("sys.exit") as mock_exit:
                            main()
                            mock_exit.assert_called_once_with(0)

    @patch("acli.subprocess.run")
    def test_main_git_protection_env_modes(self, mock_run):
        mock_run.return_value = MagicMock(stdout="agcli-base latest\nheader line\n", returncode=0)

        fake_home = self.p_path / "fake_home"
        fake_home.mkdir()

        env_override = {
            "ACLI_GIT_MODE": "",
            "ACLI_GIT_PROTECTION": "tmpfs",
            "ACLI_GIT_HOOKS_MODE": "",
        }
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch.dict(os.environ, env_override):
                with patch("sys.argv", ["acli", str(self.p_path)]):
                    with patch("sys.exit") as mock_exit:
                        main()
                        mock_exit.assert_called_once_with(0)

        env_override_ro = {
            "ACLI_GIT_MODE": "",
            "ACLI_GIT_PROTECTION": "true",
            "ACLI_GIT_HOOKS_MODE": "",
        }
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch.dict(os.environ, env_override_ro):
                with patch("sys.argv", ["acli", str(self.p_path)]):
                    with patch("sys.exit") as mock_exit:
                        main()
                        mock_exit.assert_called_once_with(0)

    @patch("acli.subprocess.run")
    def test_main_userns_behavior(self, mock_run):
        mock_run.return_value = MagicMock(stdout="agcli-base latest\nheader line\n", returncode=0)
        fake_home = self.p_path / "fake_home"
        fake_home.mkdir()

        # Helper to extract the podman run command from mock_run calls
        def get_podman_run_cmd():
            for call_args in mock_run.call_args_list:
                args_list = call_args[0][0]
                if len(args_list) >= 2 and args_list[0] == "podman" and args_list[1] == "run":
                    return args_list
            return None

        # Case 1: default 'auto' userns, with os.getuid returning 1000 (rootless) and check_userns_supported returning True
        mock_run.reset_mock()
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("os.getuid", return_value=1000):
                with patch("sys.argv", ["acli", str(self.p_path)]):
                    with patch("sys.exit") as mock_exit:
                        main()
                        mock_exit.assert_called_once_with(0)
        cmd = get_podman_run_cmd()
        self.assertIsNotNone(cmd)
        self.assertIn("--userns=keep-id:uid=0,gid=0", cmd)

        # Case 2: default 'auto' userns, but check_userns_supported returns False
        self.mock_userns_supported.return_value = False
        mock_run.reset_mock()
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("os.getuid", return_value=1000):
                with patch("sys.argv", ["acli", str(self.p_path)]):
                    with patch("sys.exit") as mock_exit:
                        main()
                        mock_exit.assert_called_once_with(0)
        cmd = get_podman_run_cmd()
        self.assertIsNotNone(cmd)
        userns_flags = [arg for arg in cmd if arg.startswith("--userns")]
        self.assertEqual(len(userns_flags), 0)

        # Restore userns patcher to return True
        self.mock_userns_supported.return_value = True

        # Case 3: --userns=none explicitly passed
        mock_run.reset_mock()
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("os.getuid", return_value=1000):
                with patch("sys.argv", ["acli", str(self.p_path), "--userns", "none"]):
                    with patch("sys.exit") as mock_exit:
                        main()
                        mock_exit.assert_called_once_with(0)
        cmd = get_podman_run_cmd()
        self.assertIsNotNone(cmd)
        userns_flags = [arg for arg in cmd if arg.startswith("--userns")]
        self.assertEqual(len(userns_flags), 0)

        # Case 4: --userns=keep-id explicitly passed
        mock_run.reset_mock()
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("os.getuid", return_value=1000):
                with patch("sys.argv", ["acli", str(self.p_path), "--userns", "keep-id"]):
                    with patch("sys.exit") as mock_exit:
                        main()
                        mock_exit.assert_called_once_with(0)
        cmd = get_podman_run_cmd()
        self.assertIsNotNone(cmd)
        self.assertIn("--userns=keep-id", cmd)

        # Case 5: ACLI_USERNS env var explicitly passed
        mock_run.reset_mock()
        with patch("pathlib.Path.home", return_value=fake_home):
            with patch("os.getuid", return_value=1000):
                with patch.dict(os.environ, {"ACLI_USERNS": "keep-id:uid=1000,gid=1000"}):
                    with patch("sys.argv", ["acli", str(self.p_path)]):
                        with patch("sys.exit") as mock_exit:
                            main()
                            mock_exit.assert_called_once_with(0)
        cmd = get_podman_run_cmd()
        self.assertIsNotNone(cmd)
        self.assertIn("--userns=keep-id:uid=1000,gid=1000", cmd)

    @patch("acli.subprocess.run")
    def test_check_userns_supported(self, mock_run):
        # Stop global userns patcher to test the real implementation
        self.userns_patcher.stop()
        try:
            from acli import check_userns_supported
            mock_run.side_effect = None

            # When subprocess returns 0
            mock_run.return_value = MagicMock(returncode=0)
            self.assertTrue(check_userns_supported("keep-id:uid=0,gid=0"))

            # When subprocess returns non-zero
            mock_run.return_value = MagicMock(returncode=1)
            self.assertFalse(check_userns_supported("keep-id:uid=0,gid=0"))

            # When subprocess raises exception
            mock_run.side_effect = Exception("error")
            self.assertFalse(check_userns_supported("keep-id:uid=0,gid=0"))
        finally:
            # Restart the patcher so other tests are unaffected
            self.mock_userns_supported = self.userns_patcher.start()

    def test_filter_mounts(self):
        from acli import filter_mounts

        mounted = set()
        mounts_list = [
            "-v", "/host/path1:/container/path1:ro",
            "-v", "/host/path2:/container/path1",
            "-v", "/host/path3:/container/path2",
            "--tmpfs", "/container/path2",
            "-e", "SOME_ENV=1",
            "-v", "/host/path4:/container/path4"
        ]

        result = filter_mounts(mounts_list, mounted)
        expected = [
            "-v", "/host/path1:/container/path1:ro",
            "-v", "/host/path3:/container/path2",
            "-e", "SOME_ENV=1",
            "-v", "/host/path4:/container/path4"
        ]
        self.assertEqual(result, expected)
        self.assertIn(str(Path("/container/path1").resolve()), mounted)
        self.assertIn(str(Path("/container/path2").resolve()), mounted)
        self.assertIn(str(Path("/container/path4").resolve()), mounted)

    @patch("acli.subprocess.run")
    def test_main_entrypoint_block(self, mock_run):
        mock_run.return_value = MagicMock(stdout="agcli-base latest\nheader line\n", returncode=0)
        acli_path = Path("/home/adam/Projekty/Python/acli/acli.py")
        with patch("sys.argv", ["acli", str(self.p_path)]):
            with patch("sys.exit"):
                runpy.run_path(str(acli_path), run_name="__main__")


if __name__ == "__main__":
    unittest.main()
