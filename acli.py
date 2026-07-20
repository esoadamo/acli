#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path

CONTAINER_SETUP = r"""set -xEeuo pipefail

# Map root's home directory to the host's home path
if [ "$HOST_HOME" != "/root" ]; then
    mkdir -p "$HOST_HOME"
    # Copy the default skeleton files (like .profile or .bashrc if they exist)
    cp -a /root/. "$HOST_HOME"/
    rm -rf /root
    ln -s "$HOST_HOME" /root
    # Update passwd file so root's home directory officially matches HOST_HOME
    sed -i "s|:/root:|:$HOST_HOME:|g" /etc/passwd
    export HOME="$HOST_HOME"
fi

if ! curl --version &> /dev/null ; then
    apt-get update
    apt-get -y install nano micro
    apt-get -y install curl git wget unzip
    apt-get -y install build-essential
    apt-get install -y mingw-w64 binutils-mingw-w64 musl-tools
fi

if ! volta --version &> /dev/null ; then
    curl https://get.volta.sh | bash
    echo 'export PATH="$HOME/.volta/bin/:$PATH"' >> "$HOME/.bashrc"
    . "$HOME/.bashrc"
    volta install node
fi

if ! rustup --version &> /dev/null ; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi

if ! uv &> /dev/null ; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    . "$HOME/.local/bin/env"
    uv python install

    mkdir -p "$HOME/.local/bin"
    ln -sf "$(uv python find)" "$HOME/.local/bin/python"
    ln -sf "$(uv python find)" "$HOME/.local/bin/python3"
fi

if ! agy --help &> /dev/null ; then
    curl -fsSL https://antigravity.google/cli/install.sh | bash
    echo 'alias agy="agy --dangerously-skip-permissions"' >> "$HOME/.bashrc"
fi

if ! copilot --help &> /dev/null; then
    curl -fsSL https://gh.io/copilot-install | bash
fi

if ! vibe --version &> /dev/null; then
    curl -LsSf https://mistral.ai/vibe/install.sh | bash
    echo 'alias vibe="vibe --agent auto-approve"' >> "$HOME/.bashrc"
fi

if ! cn --version &> /dev/null; then
    curl -fsSL https://raw.githubusercontent.com/continuedev/continue/main/extensions/cli/scripts/install.sh | bash
    # Note: /root/ is now a symlink to $HOST_HOME, so this hardcoded path still works perfectly.
    echo 'alias cn="/root/.volta/tools/image/node/*/bin/cn --allow \"*\""' >> "$HOME/.bashrc"
fi

if ! pi --version &> /dev/null; then
    curl -fsSL https://pi.dev/install.sh | sh
fi

if ! udocker --version &> /dev/null ; then
    curl -L https://github.com/indigo-dc/udocker/releases/download/1.3.17/udocker-1.3.17.tar.gz > /tmp/udocker-1.3.17.tar.gz
    curl -L https://github.com/jorge-lip/udocker-builds/raw/master/tarballs/udocker-englib-1.2.11.tar.gz > /tmp/udocker-englib-1.2.11.tar.gz
    tar zxvf /tmp/udocker-1.3.17.tar.gz -C /tmp

    mkdir -p "$HOME/.local/bin"
    mv /tmp/udocker-1.3.17 "$HOME/.local/udocker-1.3.17"

    cat << 'UDOCKER_WRAPPER' > "$HOME/.local/bin/udocker"
#!/bin/bash
exec "$HOME/.local/udocker-1.3.17/udocker/udocker" --allow-root "$@"
UDOCKER_WRAPPER

    chmod +x "$HOME/.local/bin/udocker"

    echo 'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"' >> "$HOME/.bashrc"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    cat << 'DOCKER_WRAPPER' > "$HOME/.local/bin/docker"
#!/bin/bash
echo "Warning! This is not docker, this is udocker!"
echo "See https://indigo-dc.github.io/udocker/user_manual.html for more details"
echo
udocker "$@"
DOCKER_WRAPPER

    chmod +x "$HOME/.local/bin/docker"

    export UDOCKER_TARBALL=/tmp/udocker-englib-1.2.11.tar.gz
    udocker install
fi
rm -rv /tmp/*
"""


def main():
    parser = argparse.ArgumentParser(description="acli - Podman container dev environment launcher")
    parser.add_argument("project_dir", help="Path to project directory")
    parser.add_argument("--git-mode", choices=["ro", "tmpfs", "rw"], default=None, help="Git protection mode (default: ro)")
    parser.add_argument("--git-hooks-mode", choices=["ro", "tmpfs", "rw"], default=None, help="Git hooks protection mode (default: tmpfs if git-mode is rw, otherwise ro)")
    parser.add_argument("--workspace-protection", action=argparse.BooleanOptionalAction, default=None, help="Protect IDE run configs and .envrc as read-only")
    parser.add_argument("--mask-env", action=argparse.BooleanOptionalAction, default=None, help="Mask .env* files as empty 0-byte files")
    parser.add_argument("--tools-ro", action=argparse.BooleanOptionalAction, default=None, help="Mount tool root directories as read-only")
    parser.add_argument("--tools", default=None, help="Comma-separated tools to mount (copilot, vibe, antigravity)")
    parser.add_argument("--memory", default=None, help="Memory limit for container (default: 16G)")

    args = parser.parse_args()

    project_path = Path(args.project_dir)
    if not project_path.is_dir():
        print(f"E: '{args.project_dir}' does not exist", file=sys.stderr)
        sys.exit(1)

    project_dir = str(project_path.resolve())

    # Check if agcli-base image exists
    res = subprocess.run(
        ["podman", "images", "--filter", "reference=agcli-base"],
        capture_output=True,
        text=True,
    )
    lines = [l for l in res.stdout.strip().splitlines() if l.strip()]
    if len(lines) <= 1:
        subprocess.run(["podman", "rm", "agcli-base", "debian"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        host_home = os.environ.get("HOME", "/root")
        proc = subprocess.Popen(
            ["podman", "run", "-i", "-e", f"HOST_HOME={host_home}", "--name", "agcli-base", "debian", "bash"],
            stdin=subprocess.PIPE,
        )
        proc.communicate(input=CONTAINER_SETUP.encode())
        if proc.returncode != 0:
            sys.exit(proc.returncode)
        subprocess.run(["podman", "commit", "agcli-base", "agcli-base"], check=True)
        subprocess.run(["podman", "rm", "agcli-base"], check=True)

    # Resolution order: CLI Arguments > Environment Variables > Defaults
    acli_memory = args.memory or os.environ.get("ACLI_MEMORY", "16G")
    acli_tools_str = args.tools or os.environ.get("ACLI_TOOLS", "copilot,vibe,antigravity")

    if args.tools_ro is not None:
        acli_tools_ro = args.tools_ro
    else:
        acli_tools_ro = os.environ.get("ACLI_TOOLS_RO", "true").strip().lower() not in ("0", "false", "no", "off")

    if args.git_mode is not None:
        git_mode = args.git_mode.strip().lower()
    else:
        git_mode = os.environ.get("ACLI_GIT_MODE", "").strip().lower()
        if not git_mode:
            git_prot = os.environ.get("ACLI_GIT_PROTECTION", "true").strip().lower()
            if git_prot in ("0", "false", "no", "off", "rw", "readwrite"):
                git_mode = "rw"
            elif git_prot == "tmpfs":
                git_mode = "tmpfs"
            else:
                git_mode = "ro"

    if args.git_hooks_mode is not None:
        git_hooks_mode = args.git_hooks_mode.strip().lower()
    else:
        git_hooks_mode = os.environ.get("ACLI_GIT_HOOKS_MODE", "").strip().lower()
        if not git_hooks_mode:
            git_hooks_mode = "ro" if git_mode == "ro" else "tmpfs"

    if args.workspace_protection is not None:
        workspace_protection = args.workspace_protection
    else:
        workspace_protection = os.environ.get("ACLI_WORKSPACE_PROTECTION", "true").strip().lower() not in ("0", "false", "no", "off")

    if args.mask_env is not None:
        mask_env_files = args.mask_env
    else:
        mask_env_files = os.environ.get("ACLI_MASK_ENV", "true").strip().lower() not in ("0", "false", "no", "off")

    volumes = []
    home_path = Path.home()
    ro_suffix = ":ro" if acli_tools_ro else ""

    for tool in acli_tools_str.split(","):
        t = tool.strip()
        if t == "copilot" and (home_path / ".copilot").is_dir():
            copilot_dir = home_path / ".copilot"
            volumes.extend(["-v", f"{copilot_dir}:{copilot_dir}{ro_suffix}"])
            if acli_tools_ro:
                for sub in ["session", "sessions", "logs", "cache", "tmp"]:
                    s_dir = copilot_dir / sub
                    s_dir.mkdir(parents=True, exist_ok=True)
                    volumes.extend(["-v", f"{s_dir}:{s_dir}"])
        elif t == "vibe" and (home_path / ".vibe").is_dir():
            vibe_dir = home_path / ".vibe"
            volumes.extend(["-v", f"{vibe_dir}:{vibe_dir}{ro_suffix}"])
            if acli_tools_ro:
                for sub in ["logs", "cache", "tmp", "session", "sessions"]:
                    s_dir = vibe_dir / sub
                    s_dir.mkdir(parents=True, exist_ok=True)
                    volumes.extend(["-v", f"{s_dir}:{s_dir}"])
        elif t == "antigravity" and (home_path / ".gemini" / "antigravity-cli").is_dir():
            ag_dir = home_path / ".gemini" / "antigravity-cli"
            volumes.extend(["-v", f"{ag_dir}:{ag_dir}{ro_suffix}"])
            if acli_tools_ro:
                for sub in ["brain", "conversations", "logs", "cache", "state", "tmp", "sessions", "session", ".system_generated"]:
                    s_dir = ag_dir / sub
                    s_dir.mkdir(parents=True, exist_ok=True)
                    volumes.extend(["-v", f"{s_dir}:{s_dir}"])

    p_path = Path(project_dir)

    # Git protection logic based on git_mode and git_hooks_mode
    git_mounts = []
    git_entries = set()
    root_dot_git = p_path / ".git"
    if root_dot_git.exists():
        git_entries.add(root_dot_git)

    for dot_git in p_path.rglob(".git"):
        git_entries.add(dot_git)

    user_configs = [home_path / ".gitconfig", home_path / ".config" / "git" / "config"]

    if git_mode == "ro":
        for dot_git in sorted(git_entries):
            if dot_git.is_dir() or dot_git.is_file():
                git_mounts.extend(["-v", f"{dot_git}:{dot_git}:ro"])
                if dot_git.is_file():
                    try:
                        content = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
                        if content.startswith("gitdir:"):
                            gitdir_str = content.split("gitdir:", 1)[1].strip()
                            gitdir_path = Path(gitdir_str)
                            if not gitdir_path.is_absolute():
                                gitdir_path = (dot_git.parent / gitdir_path).resolve()
                            if gitdir_path.exists():
                                git_mounts.extend(["-v", f"{gitdir_path}:{gitdir_path}:ro"])
                    except Exception:
                        pass
        if git_hooks_mode == "tmpfs":
            for dot_git in sorted(git_entries):
                if dot_git.is_dir():
                    git_mounts.extend(["--tmpfs", str(dot_git / "hooks")])
        for u_cfg in user_configs:
            if u_cfg.is_file():
                git_mounts.extend(["-v", f"{u_cfg}:{u_cfg}:ro"])
    else:
        # git_mode is "rw" or "tmpfs"
        for dot_git in sorted(git_entries):
            if dot_git.is_dir():
                cfg = dot_git / "config"
                if cfg.is_file():
                    git_mounts.extend(["-v", f"{cfg}:{cfg}:ro"])
            elif dot_git.is_file():
                try:
                    content = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
                    if content.startswith("gitdir:"):
                        gitdir_str = content.split("gitdir:", 1)[1].strip()
                        gitdir_path = Path(gitdir_str)
                        if not gitdir_path.is_absolute():
                            gitdir_path = (dot_git.parent / gitdir_path).resolve()
                        if gitdir_path.exists():
                            cfg = gitdir_path / "config"
                            if cfg.is_file():
                                git_mounts.extend(["-v", f"{cfg}:{cfg}:ro"])
                except Exception:
                    pass

        if git_hooks_mode == "tmpfs":
            for dot_git in sorted(git_entries):
                if dot_git.is_dir():
                    git_mounts.extend(["--tmpfs", str(dot_git / "hooks")])
                elif dot_git.is_file():
                    try:
                        content = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
                        if content.startswith("gitdir:"):
                            gitdir_str = content.split("gitdir:", 1)[1].strip()
                            gitdir_path = Path(gitdir_str)
                            if not gitdir_path.is_absolute():
                                gitdir_path = (dot_git.parent / gitdir_path).resolve()
                            if gitdir_path.exists():
                                git_mounts.extend(["--tmpfs", str(gitdir_path / "hooks")])
                    except Exception:
                        pass
        elif git_hooks_mode == "ro":
            for dot_git in sorted(git_entries):
                if dot_git.is_dir():
                    git_mounts.extend(["-v", f"{dot_git / 'hooks'}:{dot_git / 'hooks'}:ro"])
                elif dot_git.is_file():
                    try:
                        content = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
                        if content.startswith("gitdir:"):
                            gitdir_str = content.split("gitdir:", 1)[1].strip()
                            gitdir_path = Path(gitdir_str)
                            if not gitdir_path.is_absolute():
                                gitdir_path = (dot_git.parent / gitdir_path).resolve()
                            if gitdir_path.exists():
                                git_mounts.extend(["-v", f"{gitdir_path / 'hooks'}:{gitdir_path / 'hooks'}:ro"])
                    except Exception:
                        pass

        for u_cfg in user_configs:
            if u_cfg.is_file():
                git_mounts.extend(["-v", f"{u_cfg}:{u_cfg}:ro"])

    # Workspace persistence protection: mount IDE run configs & direnv as read-only
    workspace_ro_mounts = []
    if workspace_protection:
        ws_ro_targets = [
            p_path / ".envrc",
            p_path / ".vscode" / "tasks.json",
            p_path / ".vscode" / "launch.json",
            p_path / ".vscode" / "settings.json",
            p_path / ".idea",
        ]
        for ws_item in ws_ro_targets:
            if ws_item.exists():
                workspace_ro_mounts.extend(["-v", f"{ws_item}:{ws_item}:ro"])

    # Mask .env* files by default as 0-byte empty files (except .env.acli)
    env_mask_mounts = []
    if mask_env_files:
        for env_file in p_path.rglob(".env*"):
            if env_file.is_file() and env_file.name != ".env.acli":
                env_mask_mounts.extend(["-v", f"/dev/null:{env_file}"])

    cmd = (
        ["podman", "run", "-it", "--rm"]
        + volumes
        + ["-v", f"{project_dir}:{project_dir}"]
        + git_mounts
        + workspace_ro_mounts
        + env_mask_mounts
        + ["--workdir", project_dir, "--memory", acli_memory, "agcli-base", "bash"]
    )

    res = subprocess.run(cmd)
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()
