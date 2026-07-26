#!/usr/bin/env python3
import argparse
import fnmatch
import os
import re
import secrets
import shutil
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

if ! claude --version &> /dev/null; then
    curl -fsSL https://claude.ai/install.sh | bash
    echo 'alias claude="IS_SANDBOX=1 claude --dangerously-skip-permissions"' >> "$HOME/.bashrc"
fi

if ! udocker --version &> /dev/null ; then
    curl -L https://github.com/indigo-dc/udocker/releases/download/1.3.17/udocker-1.3.17.tar.gz > /tmp/udocker-1.3.17.tar.gz
    curl -L https://github.com/jorge-lip/udocker-builds/raw/master/tarballs/udocker-englib-1.2.11.tar.gz > /tmp/udocker-englib-1.2.11.tar.gz
    tar zxvf /tmp/udocker-1.3.17.tar.gz -C /tmp

    mkdir -p "$HOME/.local/bin"
    mv /tmp/udocker-1.3.17 "$HOME/.local/udocker-1.3.17"

    cat << 'UDOCKER_WRAPPER' > "$HOME/.local/bin/udocker"
#!/bin/bash
UDOCKER_BIN="$HOME/.local/udocker-1.3.17/udocker/udocker"

if [ "$1" = "run" ]; then
    shift
    RUN_FLAGS=()
    TARGET=""
    CMD_ARGS=()

    while [ $# -gt 0 ]; do
        case "$1" in
            --name)
                RUN_FLAGS+=("$1" "$2")
                shift 2
                ;;
            --name=*)
                RUN_FLAGS+=("$1")
                shift
                ;;
            -v|--volume|-e|--env|-w|--workdir|-u|--user|-p|--publish)
                RUN_FLAGS+=("$1" "$2")
                shift 2
                ;;
            -v=*|-e=*|-w=*|-u=*|-p=*)
                RUN_FLAGS+=("$1")
                shift
                ;;
            -*)
                RUN_FLAGS+=("$1")
                shift
                ;;
            *)
                TARGET="$1"
                shift
                CMD_ARGS=("$@")
                break
                ;;
        esac
    done

    if [ -z "$TARGET" ]; then
        exec "$UDOCKER_BIN" --allow-root run --help
    fi

    # Check if TARGET is an existing container name or ID
    if "$UDOCKER_BIN" --allow-root ps 2>/dev/null | grep -q -E "\b${TARGET}\b"; then
        CID="$TARGET"
    else
        # Check if TARGET image is present, pull if missing
        if ! "$UDOCKER_BIN" --allow-root images 2>/dev/null | grep -q -E "^\s*${TARGET}\b|\s*${TARGET}:"; then
            echo "Image '${TARGET}' not found locally. Pulling via udocker..."
            "$UDOCKER_BIN" --allow-root pull "$TARGET" || exit $?
        fi
        CID=$("$UDOCKER_BIN" --allow-root create "$TARGET" 2>/dev/null | tail -n1 | tr -d '\r')
        if [ -z "$CID" ]; then
            echo "Error: Failed to create container for '$TARGET'" >&2
            exit 1
        fi
    fi

    exec "$UDOCKER_BIN" --allow-root run "${RUN_FLAGS[@]}" "$CID" "${CMD_ARGS[@]}"
else
    exec "$UDOCKER_BIN" --allow-root "$@"
fi
UDOCKER_WRAPPER

    chmod +x "$HOME/.local/bin/udocker"

    echo 'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"' >> "$HOME/.bashrc"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    cat << 'DOCKER_WRAPPER' > "$HOME/.local/bin/docker"
#!/bin/bash
if [ $# -eq 0 ]; then
    exec udocker --help
fi

CMD="$1"
shift

case "$CMD" in
    compose)
        exec docker-compose "$@"
        ;;
    pull)
        exec udocker pull "$@"
        ;;
    images)
        exec udocker images "$@"
        ;;
    ps)
        exec udocker ps "$@"
        ;;
    rm)
        exec udocker rm "$@"
        ;;
    rmi)
        exec udocker rmi "$@"
        ;;
    run)
        RM_CONTAINER=false
        ENV_ARGS=()
        VOL_ARGS=()
        WORKDIR=""
        CONTAINER_NAME=""
        IMAGE=""
        COMMAND=()

        while [ $# -gt 0 ]; do
            case "$1" in
                --rm)
                    RM_CONTAINER=true
                    shift
                    ;;
                -i|-t|-it|-ti)
                    shift
                    ;;
                -e|--env)
                    ENV_ARGS+=("-e" "$2")
                    shift 2
                    ;;
                -e=*)
                    ENV_ARGS+=("-e" "${1#*=}")
                    shift
                    ;;
                -v|--volume)
                    VOL_ARGS+=("-v" "$2")
                    shift 2
                    ;;
                -v=*)
                    VOL_ARGS+=("-v" "${1#*=}")
                    shift
                    ;;
                -w|--workdir)
                    WORKDIR="$2"
                    shift 2
                    ;;
                -w=*)
                    WORKDIR="${1#*=}"
                    shift
                    ;;
                --name)
                    CONTAINER_NAME="$2"
                    shift 2
                    ;;
                --name=*)
                    CONTAINER_NAME="${1#*=}"
                    shift
                    ;;
                -*)
                    shift
                    ;;
                *)
                    IMAGE="$1"
                    shift
                    COMMAND=("$@")
                    break
                    ;;
            esac
        done

        if [ -z "$IMAGE" ]; then
            echo "Error: No image specified for docker run." >&2
            exit 1
        fi

        RUN_OPTS=()
        TMP_NAME=""
        if [ "$RM_CONTAINER" = true ] && [ -z "$CONTAINER_NAME" ]; then
            TMP_NAME="docker_run_tmp_$$"
            RUN_OPTS+=("--name=$TMP_NAME")
        elif [ -n "$CONTAINER_NAME" ]; then
            RUN_OPTS+=("--name=$CONTAINER_NAME")
        fi

        if [ -n "$WORKDIR" ]; then
            RUN_OPTS+=("-w" "$WORKDIR")
        fi
        RUN_OPTS+=("${ENV_ARGS[@]}")
        RUN_OPTS+=("${VOL_ARGS[@]}")

        udocker run "${RUN_OPTS[@]}" "$IMAGE" "${COMMAND[@]}"
        EXIT_CODE=$?

        if [ "$RM_CONTAINER" = true ] && [ -n "$TMP_NAME" ]; then
            udocker rm "$TMP_NAME" >/dev/null 2>&1
        fi

        exit $EXIT_CODE
        ;;
    *)
        exec udocker "$CMD" "$@"
        ;;
esac
DOCKER_WRAPPER

    cat << 'COMPOSE_WRAPPER' > "$HOME/.local/bin/docker-compose"
#!/usr/bin/env python3
import argparse
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def parse_simple_yaml(text):
    services = {}
    current_service = None
    current_key = None

    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())
        if stripped == "services:":
            continue

        if indent == 2 and line.strip().endswith(":"):
            current_service = line.strip()[:-1]
            services[current_service] = {}
            current_key = None
            continue

        if current_service and indent == 4:
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                k = k.strip()
                v = v.strip()
                if not v:
                    current_key = k
                    services[current_service][k] = []
                else:
                    v = v.strip("\"'")
                    services[current_service][k] = v
                    current_key = None
            continue

        if current_service and current_key and indent >= 6:
            item = stripped.lstrip("- ").strip("\"'")
            if isinstance(services[current_service].get(current_key), list):
                services[current_service][current_key].append(item)

    return {"services": services}


def load_compose_file(filepath=None):
    if filepath:
        paths = [Path(filepath)]
    else:
        paths = [
            Path("docker-compose.yml"),
            Path("docker-compose.yaml"),
            Path("compose.yml"),
            Path("compose.yaml"),
        ]

    chosen = None
    for p in paths:
        if p.is_file():
            chosen = p
            break

    if not chosen:
        print("Error: No docker-compose.yml or compose.yml file found.", file=sys.stderr)
        sys.exit(1)

    content = chosen.read_text(encoding="utf-8")
    if yaml is not None:
        try:
            data = yaml.safe_load(content)
            if data and "services" in data:
                return data, chosen
        except Exception:
            pass

    return parse_simple_yaml(content), chosen


def find_udocker_bin():
    home = Path.home()
    local_udocker = home / ".local" / "bin" / "udocker"
    if local_udocker.is_file() and os.access(local_udocker, os.X_OK):
        return str(local_udocker)
    return "udocker"


def get_pid_file(project_name, service_name):
    tmp_dir = Path("/tmp") / ".docker_compose_pids"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir / f"{project_name}_{service_name}.pid"


def cmd_up(compose_data, compose_file, detached=False):
    project_name = compose_file.parent.resolve().name.lower()
    project_name = re.sub(r"[^a-z0-9_-]", "", project_name) or "compose"
    udocker_bin = find_udocker_bin()

    services = compose_data.get("services", {})
    if not services:
        print("No services found in compose file.", file=sys.stderr)
        return

    for service_name, config in services.items():
        if not isinstance(config, dict):
            continue

        image = config.get("image")
        if not image:
            print(f"Error: Service '{service_name}' has no 'image' specified.", file=sys.stderr)
            continue

        container_name = config.get("container_name") or f"{project_name}_{service_name}_1"

        subprocess.run([udocker_bin, "rm", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        run_args = [udocker_bin, "run"]
        run_args.extend(["--name", container_name])

        volumes = config.get("volumes", [])
        if isinstance(volumes, list):
            for v in volumes:
                run_args.extend(["-v", str(v)])

        env = config.get("environment", [])
        if isinstance(env, list):
            for e in env:
                run_args.extend(["-e", str(e)])
        elif isinstance(env, dict):
            for k, v in env.items():
                run_args.extend(["-e", f"{k}={v}"])

        cmd = config.get("command")
        cmd_list = []
        if isinstance(cmd, str):
            if cmd.startswith("[") and cmd.endswith("]"):
                try:
                    cmd_list = ast.literal_eval(cmd)
                except Exception:
                    cmd_list = [x.strip("\"' ") for x in cmd[1:-1].split(",")]
            else:
                cmd_list = cmd.split()
        elif isinstance(cmd, list):
            cmd_list = [str(x) for x in cmd]

        full_cmd = run_args + [image] + cmd_list

        print(f"Starting {container_name} ({image})...")

        if detached:
            pid_file = get_pid_file(project_name, service_name)
            proc = subprocess.Popen(
                full_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            pid_file.write_text(str(proc.pid))
            print(f"Started {container_name} in background (PID {proc.pid})")
        else:
            try:
                subprocess.run(full_cmd)
            except KeyboardInterrupt:
                print(f"\nStopping {container_name}...")
                cmd_down(compose_data, compose_file)
                break


def cmd_down(compose_data, compose_file):
    project_name = compose_file.parent.resolve().name.lower()
    project_name = re.sub(r"[^a-z0-9_-]", "", project_name) or "compose"
    udocker_bin = find_udocker_bin()

    services = compose_data.get("services", {})
    for service_name, config in services.items():
        if not isinstance(config, dict):
            continue

        container_name = config.get("container_name") or f"{project_name}_{service_name}_1"

        pid_file = get_pid_file(project_name, service_name)
        if pid_file.is_file():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                print(f"Stopped background process PID {pid} for {container_name}")
            except Exception:
                pass
            try:
                pid_file.unlink()
            except Exception:
                pass

        print(f"Removing container {container_name}...")
        subprocess.run([udocker_bin, "rm", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description="docker-compose wrapper for udocker")
    parser.add_argument("-f", "--file", help="Path to compose file")
    subparsers = parser.add_subparsers(dest="subcommand")

    up_parser = subparsers.add_parser("up", help="Build, (re)create, start, and attach to containers for a service")
    up_parser.add_argument("-d", "--detach", action="store_true", help="Detached mode: Run containers in the background")

    down_parser = subparsers.add_parser("down", help="Stop and remove containers, networks, images, and volumes")

    ps_parser = subparsers.add_parser("ps", help="List containers")

    args, extra = parser.parse_known_args()

    compose_data, compose_file = load_compose_file(args.file)

    if args.subcommand == "up":
        cmd_up(compose_data, compose_file, detached=args.detach)
    elif args.subcommand == "down":
        cmd_down(compose_data, compose_file)
    elif args.subcommand == "ps":
        udocker_bin = find_udocker_bin()
        subprocess.run([udocker_bin, "ps"])
    else:
        if not args.subcommand:
            parser.print_help()


if __name__ == "__main__":
    main()
COMPOSE_WRAPPER

    cat << 'PODMAN_WRAPPER' > "$HOME/.local/bin/podman"
#!/bin/bash
exec docker "$@"
PODMAN_WRAPPER

    cat << 'PODMAN_COMPOSE_WRAPPER' > "$HOME/.local/bin/podman-compose"
#!/bin/bash
exec docker-compose "$@"
PODMAN_COMPOSE_WRAPPER

    chmod +x "$HOME/.local/bin/docker" "$HOME/.local/bin/docker-compose" "$HOME/.local/bin/podman" "$HOME/.local/bin/podman-compose"

    echo 'alias podman="docker"' >> "$HOME/.bashrc"
    echo 'alias podman-compose="docker-compose"' >> "$HOME/.bashrc"

    export UDOCKER_TARBALL=/tmp/udocker-englib-1.2.11.tar.gz
    udocker install
fi
rm -rv /tmp/*
"""


def copy_with_cow_rsync_fallback(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try Copy-On-Write (reflink) first
    try:
        res = subprocess.run(
            ["cp", "--reflink=always", "-a", str(src), str(dst)],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return
    except Exception:
        pass

    # 2. Try rsync (skips unmodified files)
    try:
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            rsync_src = str(src) + "/"
            rsync_dst = str(dst) + "/"
        else:
            rsync_src = str(src)
            rsync_dst = str(dst)

        res = subprocess.run(
            ["rsync", "-a", rsync_src, rsync_dst],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return
    except Exception:
        pass

    # 3. Fallback to classical copy
    if not dst.exists():
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
    else:
        if src.is_dir():
            for root, _, files in os.walk(src):
                rel = Path(root).relative_to(src)
                target_dir = dst / rel
                target_dir.mkdir(parents=True, exist_ok=True)
                for f in files:
                    s_file = Path(root) / f
                    d_file = target_dir / f
                    if not d_file.exists() or s_file.stat().st_mtime > d_file.stat().st_mtime:
                        shutil.copy2(s_file, d_file)
        else:
            if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                shutil.copy2(src, dst)


def get_ignored_paths(p_path: Path) -> list[Path]:
    gitignore_files = list(p_path.rglob(".gitignore"))
    if not gitignore_files:
        return []

    ignored_rel_paths = set()

    # Try git command first if available and inside git work tree
    try:
        res = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
            cwd=str(p_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                line = line.strip().rstrip("/")
                if line:
                    ignored_rel_paths.add(Path(line))
    except Exception:
        pass

    # Fallback/supplemental pattern matching from .gitignore files
    if not ignored_rel_paths:
        for gi_file in gitignore_files:
            gi_dir = gi_file.parent
            try:
                content = gi_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            patterns = []
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)

            if not patterns:
                continue

            for item in gi_dir.rglob("*"):
                if ".git" in item.parts or "git" in item.parts:
                    continue
                try:
                    rel_to_gi = item.relative_to(gi_dir)
                    rel_to_proj = item.relative_to(p_path)
                except ValueError:
                    continue

                is_dir = item.is_dir()
                matched = False
                for pat in patterns:
                    negated = False
                    if pat.startswith("!"):
                        negated = True
                        pat = pat[1:]

                    dir_only = pat.endswith("/")
                    if dir_only:
                        pat = pat.rstrip("/")
                        if not is_dir:
                            continue

                    target_str = str(rel_to_gi)
                    if "/" not in pat:
                        if fnmatch.fnmatch(item.name, pat) or fnmatch.fnmatch(target_str, pat):
                            matched = not negated
                    else:
                        pat = pat.lstrip("/")
                        if fnmatch.fnmatch(target_str, pat) or fnmatch.fnmatch(target_str, pat + "/*"):
                            matched = not negated

                if matched:
                    ignored_rel_paths.add(rel_to_proj)

    # Filter out forbidden paths (.git folder, non-existent paths)
    valid_paths = set()
    for rel_p in ignored_rel_paths:
        if ".git" in rel_p.parts or "git" in rel_p.parts:
            continue
        abs_p = p_path / rel_p
        if not abs_p.exists():
            continue
        valid_paths.add(rel_p)

    # Prune redundant child paths whose parent is already included
    pruned_paths = []
    for rel_p in sorted(valid_paths):
        has_parent_in_valid = False
        for parent in rel_p.parents:
            if parent != Path(".") and parent in valid_paths:
                has_parent_in_valid = True
                break
        if not has_parent_in_valid:
            pruned_paths.append(rel_p)

    return pruned_paths


def check_userns_supported(userns_option: str) -> bool:
    try:
        # Run a quick check using podman run with the specified userns option.
        # Since 'agcli-base' is guaranteed to exist at this point in the main execution flow,
        # we can use it to perform a quick, no-op run.
        res = subprocess.run(
            ["podman", "run", "--rm", f"--userns={userns_option}", "agcli-base", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0
    except Exception:
        return False


def filter_mounts(mount_args: list[str], mounted_destinations: set[str]) -> list[str]:
    filtered = []
    i = 0
    while i < len(mount_args):
        if i + 1 >= len(mount_args):
            filtered.append(mount_args[i])
            break

        opt = mount_args[i]
        val = mount_args[i+1]

        dest = None
        if opt == "-v":
            parts = val.split(":")
            if len(parts) >= 2:
                dest = parts[1]
        elif opt == "--tmpfs":
            dest = val

        if dest:
            dest_path = str(Path(dest).resolve())
            if dest_path in mounted_destinations:
                i += 2
                continue
            mounted_destinations.add(dest_path)

        filtered.extend([opt, val])
        i += 2
    return filtered


def main():
    parser = argparse.ArgumentParser(description="acli - Podman container dev environment launcher")
    parser.add_argument("project_dir", help="Path to project directory")
    parser.add_argument("--git-mode", choices=["ro", "tmpfs", "rw"], default=None, help="Git protection mode (default: ro)")
    parser.add_argument("--git-hooks-mode", choices=["ro", "tmpfs", "rw"], default=None, help="Git hooks protection mode (default: tmpfs if git-mode is rw, otherwise ro)")
    parser.add_argument("--gitignore-mode", choices=["mask", "ro", "rw"], default=None, help="Gitignore protection mode (default: mask)")
    parser.add_argument("--workspace-protection", action=argparse.BooleanOptionalAction, default=None, help="Protect IDE run configs and .envrc as read-only")
    parser.add_argument("--mask-env", action=argparse.BooleanOptionalAction, default=None, help="Mask .env* files as empty 0-byte files")
    parser.add_argument("--tools-ro", action=argparse.BooleanOptionalAction, default=None, help="Mount tool root directories as read-only")
    parser.add_argument("--persistence", choices=["per-project", "global"], default=None, help="Tool state persistence mode (default: per-project)")
    parser.add_argument("--tools", default=None, help="Comma-separated tools to mount (copilot, vibe, antigravity, claude)")
    parser.add_argument("--memory", default=None, help="Memory limit for container (default: 16G)")
    parser.add_argument("--userns", default=None, help="User namespace mode for Podman (e.g. keep-id:uid=0,gid=0, none)")

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
    acli_tools_str = args.tools or os.environ.get("ACLI_TOOLS", "copilot,vibe,antigravity,claude")

    if args.persistence is not None:
        acli_persistence = args.persistence.strip().lower()
    else:
        acli_persistence = os.environ.get("ACLI_PERSISTENCE", "per-project").strip().lower()
        if acli_persistence not in ("per-project", "global"):
            acli_persistence = "per-project"

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

    if args.gitignore_mode is not None:
        gitignore_mode = args.gitignore_mode.strip().lower()
    else:
        gitignore_mode = os.environ.get("ACLI_GITIGNORE_MODE", "mask").strip().lower()
        if gitignore_mode not in ("mask", "ro", "rw"):
            gitignore_mode = "mask"

    if args.workspace_protection is not None:
        workspace_protection = args.workspace_protection
    else:
        workspace_protection = os.environ.get("ACLI_WORKSPACE_PROTECTION", "true").strip().lower() not in ("0", "false", "no", "off")

    if args.mask_env is not None:
        mask_env_files = args.mask_env
    else:
        mask_env_files = os.environ.get("ACLI_MASK_ENV", "true").strip().lower() not in ("0", "false", "no", "off")

    if args.userns is not None:
        acli_userns = args.userns.strip().lower()
    else:
        acli_userns = os.environ.get("ACLI_USERNS", "auto").strip().lower()
        if not acli_userns:
            acli_userns = "auto"

    volumes = []
    home_path = Path.home()
    ro_suffix = ":ro" if acli_tools_ro else ""

    project_slug = str(project_path.resolve()).replace("/", "_").lstrip("_")
    proj_storage_root = home_path / ".acli" / "projects" / project_slug

    for tool in acli_tools_str.split(","):
        t = tool.strip()
        if t == "copilot" and (home_path / ".copilot").is_dir():
            copilot_dir = home_path / ".copilot"
            volumes.extend(["-v", f"{copilot_dir}:{copilot_dir}{ro_suffix}"])
            if acli_tools_ro:
                for sub in ["session", "sessions", "session-state"]:
                    if acli_persistence == "per-project":
                        host_s_dir = proj_storage_root / "copilot" / sub
                    else:
                        host_s_dir = copilot_dir / sub
                    host_s_dir.mkdir(parents=True, exist_ok=True)
                    volumes.extend(["-v", f"{host_s_dir}:{copilot_dir / sub}"])
                for tmp_sub in ["log", "logs", "cache", "tmp"]:
                    s_dir = copilot_dir / tmp_sub
                    s_dir.mkdir(parents=True, exist_ok=True)
                    volumes.extend(["--tmpfs", str(s_dir)])
                for f_name in ["command-history-state.json", "vscode.session.metadata.cache.json"]:
                    if acli_persistence == "per-project":
                        host_f = proj_storage_root / "copilot" / f_name
                        host_f.parent.mkdir(parents=True, exist_ok=True)
                        if not host_f.exists() and (copilot_dir / f_name).exists():
                            try:
                                host_f.write_bytes((copilot_dir / f_name).read_bytes())
                            except Exception:
                                host_f.touch(exist_ok=True)
                        else:
                            host_f.touch(exist_ok=True)
                        volumes.extend(["-v", f"{host_f}:{copilot_dir / f_name}"])
                    else:
                        f_path = copilot_dir / f_name
                        if f_path.exists():
                            volumes.extend(["-v", f"{f_path}:{f_path}"])
                db_file = copilot_dir / "session-store.db"
                if db_file.exists() or acli_persistence == "per-project":
                    for ext in ["", "-wal", "-shm"]:
                        f_name = f"session-store.db{ext}"
                        if acli_persistence == "per-project":
                            host_f = proj_storage_root / "copilot" / f_name
                            host_f.parent.mkdir(parents=True, exist_ok=True)
                            if not host_f.exists() and (copilot_dir / f_name).exists():
                                try:
                                    host_f.write_bytes((copilot_dir / f_name).read_bytes())
                                except Exception:
                                    host_f.touch(exist_ok=True)
                            else:
                                host_f.touch(exist_ok=True)
                            volumes.extend(["-v", f"{host_f}:{copilot_dir / f_name}"])
                        else:
                            f_path = copilot_dir / f_name
                            f_path.touch(exist_ok=True)
                            volumes.extend(["-v", f"{f_path}:{f_path}"])
        elif t == "vibe" and (home_path / ".vibe").is_dir():
            vibe_dir = home_path / ".vibe"
            volumes.extend(["-v", f"{vibe_dir}:{vibe_dir}{ro_suffix}"])
            if acli_tools_ro:
                for tmp_sub in ["log", "logs", "cache", "tmp", "session", "sessions"]:
                    s_dir = vibe_dir / tmp_sub
                    s_dir.mkdir(parents=True, exist_ok=True)
                    volumes.extend(["--tmpfs", str(s_dir)])
                for f_name in ["vibehistory", "cache.toml", "connector_bootstrap_cache.json"]:
                    if acli_persistence == "per-project":
                        host_f = proj_storage_root / "vibe" / f_name
                        host_f.parent.mkdir(parents=True, exist_ok=True)
                        if not host_f.exists() and (vibe_dir / f_name).exists():
                            try:
                                host_f.write_bytes((vibe_dir / f_name).read_bytes())
                            except Exception:
                                host_f.touch(exist_ok=True)
                        else:
                            host_f.touch(exist_ok=True)
                        volumes.extend(["-v", f"{host_f}:{vibe_dir / f_name}"])
                    else:
                        f_path = vibe_dir / f_name
                        if f_path.exists():
                            volumes.extend(["-v", f"{f_path}:{f_path}"])
        elif t == "antigravity" and (home_path / ".gemini" / "antigravity-cli").is_dir():
            ag_dir = home_path / ".gemini" / "antigravity-cli"
            volumes.extend(["-v", f"{ag_dir}:{ag_dir}{ro_suffix}"])
            if acli_tools_ro:
                for sub in ["brain", "conversations", "state", "sessions", "session", ".system_generated", "knowledge"]:
                    if acli_persistence == "per-project":
                        host_s_dir = proj_storage_root / "antigravity-cli" / sub
                    else:
                        host_s_dir = ag_dir / sub
                    host_s_dir.mkdir(parents=True, exist_ok=True)
                    volumes.extend(["-v", f"{host_s_dir}:{ag_dir / sub}"])
                for tmp_sub in ["log", "logs", "cache", "tmp", "bin", "crashes", "implicit", "scratch", "updater"]:
                    s_dir = ag_dir / tmp_sub
                    s_dir.mkdir(parents=True, exist_ok=True)
                    volumes.extend(["--tmpfs", str(s_dir)])
                for f_name in ["history.jsonl", "last_check.timestamp", "cli.log", "jetski_state.pbtxt"]:
                    if acli_persistence == "per-project":
                        host_f = proj_storage_root / "antigravity-cli" / f_name
                        host_f.parent.mkdir(parents=True, exist_ok=True)
                        if not host_f.exists() and (ag_dir / f_name).exists():
                            try:
                                host_f.write_bytes((ag_dir / f_name).read_bytes())
                            except Exception:
                                host_f.touch(exist_ok=True)
                        else:
                            host_f.touch(exist_ok=True)
                        volumes.extend(["-v", f"{host_f}:{ag_dir / f_name}"])
                    else:
                        f_path = ag_dir / f_name
                        if f_path.exists() or f_path.is_symlink():
                            volumes.extend(["-v", f"{f_path}:{f_path}"])
                db_file = ag_dir / "conversation_summaries.db"
                if db_file.exists() or acli_persistence == "per-project":
                    for ext in ["", "-wal", "-shm"]:
                        f_name = f"conversation_summaries.db{ext}"
                        if acli_persistence == "per-project":
                            host_f = proj_storage_root / "antigravity-cli" / f_name
                            host_f.parent.mkdir(parents=True, exist_ok=True)
                            if not host_f.exists() and (ag_dir / f_name).exists():
                                try:
                                    host_f.write_bytes((ag_dir / f_name).read_bytes())
                                except Exception:
                                    host_f.touch(exist_ok=True)
                            else:
                                host_f.touch(exist_ok=True)
                            volumes.extend(["-v", f"{host_f}:{ag_dir / f_name}"])
                        else:
                            f_path = ag_dir / f_name
                            f_path.touch(exist_ok=True)
                            volumes.extend(["-v", f"{f_path}:{f_path}"])
        elif t == "claude" and (home_path / ".claude").is_dir():
            claude_dir = home_path / ".claude"
            if acli_tools_ro and acli_persistence == "per-project":
                claude_storage = proj_storage_root / "claude" / "config"
                copy_with_cow_rsync_fallback(claude_dir, claude_storage)
                volumes.extend(["-v", f"{claude_storage}:{claude_dir}"])
            else:
                volumes.extend(["-v", f"{claude_dir}:{claude_dir}"])
            claude_json = home_path / ".claude.json"
            if claude_json.is_file():
                if acli_persistence == "per-project":
                    host_claude_json = proj_storage_root / "claude" / ".claude.json"
                    host_claude_json.parent.mkdir(parents=True, exist_ok=True)
                    if not host_claude_json.exists():
                        try:
                            host_claude_json.write_bytes(claude_json.read_bytes())
                        except Exception:
                            host_claude_json.touch(exist_ok=True)
                    volumes.extend(["-v", f"{host_claude_json}:{claude_json}"])
                else:
                    volumes.extend(["-v", f"{claude_json}:{claude_json}"])
            volumes.extend(["-e", "DISABLE_AUTOUPDATER=1"])
            volumes.extend(["-e", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"])

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

    # Gitignore protection logic based on gitignore_mode
    gitignore_mounts = []
    if gitignore_mode == "mask":
        masked_root = proj_storage_root / "gitignore_masked"
        ignored_paths = get_ignored_paths(p_path)
        for rel_path in ignored_paths:
            abs_host_path = p_path / rel_path
            target_in_storage = masked_root / rel_path
            copy_with_cow_rsync_fallback(abs_host_path, target_in_storage)
            gitignore_mounts.extend(["-v", f"{target_in_storage}:{abs_host_path}"])
    elif gitignore_mode == "ro":
        ignored_paths = get_ignored_paths(p_path)
        for rel_path in ignored_paths:
            abs_host_path = p_path / rel_path
            gitignore_mounts.extend(["-v", f"{abs_host_path}:{abs_host_path}:ro"])

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

    random_hex = secrets.token_hex(4)
    encoded_path = re.sub(r"[^a-zA-Z0-9_-]", "_", str(project_path.resolve()).replace("/", "_").lstrip("_"))
    container_name = f"acli-{encoded_path}-{random_hex}"

    userns_opts = []
    if acli_userns == "auto":
        if hasattr(os, "getuid") and os.getuid() != 0:
            if check_userns_supported("keep-id:uid=0,gid=0"):
                userns_opts = ["--userns=keep-id:uid=0,gid=0"]
    elif acli_userns and acli_userns not in ("none", "off", "false"):
        userns_opts = [f"--userns={acli_userns}"]

    mounted_destinations = set()
    filtered_volumes = filter_mounts(volumes, mounted_destinations)
    filtered_project_mount = filter_mounts(["-v", f"{project_dir}:{project_dir}"], mounted_destinations)
    filtered_git_mounts = filter_mounts(git_mounts, mounted_destinations)
    filtered_env_mask_mounts = filter_mounts(env_mask_mounts, mounted_destinations)
    filtered_gitignore_mounts = filter_mounts(gitignore_mounts, mounted_destinations)
    filtered_workspace_ro_mounts = filter_mounts(workspace_ro_mounts, mounted_destinations)

    cmd = (
        ["podman", "run", "-it", "--rm", "--name", container_name]
        + userns_opts
        + ["--cap-drop=ALL", "--security-opt=no-new-privileges"]
        + filtered_volumes
        + filtered_project_mount
        + filtered_git_mounts
        + filtered_gitignore_mounts
        + filtered_workspace_ro_mounts
        + filtered_env_mask_mounts
        + ["--workdir", project_dir, "--memory", acli_memory, "agcli-base", "bash"]
    )

    res = subprocess.run(cmd)
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()
