# acli

`acli` is a secure container wrapper around agentic CLIs (such as GitHub Copilot CLI, Mistral Vibe, and Google Antigravity). It launches agentic tasks inside an isolated Podman dev environment to prevent agents from breaking out ("escaping from jail"), overwriting critical host files, or reading sensitive environment secrets.

---

## Features

- **Container Isolation**: Executes agent CLIs inside an isolated Podman container (`agcli-base`).
- **Git & Hook Protection**: Prevents AI agents from tampering with `.git` history or installing malicious git hooks.
- **Workspace Protection**: Mounts IDE configurations (`.vscode`, `.idea`) and `.envrc` as read-only.
- **Secret Masking**: Automatically masks `.env*` files as 0-byte empty files inside the container (except `.env.acli`).
- **Read-Only Tool Base**: Keeps global CLI configurations read-only while isolating session state per project.

---

## Quick Start

### Prerequisites

- [Podman](https://podman.io/)
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Installation & Execution

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-repo/acli.git
   cd acli
   ```

2. **Run `acli` on a project directory:**
   ```bash
   # Run in current directory
   uv run acli .

   # Run on a specific project directory with custom options
   uv run acli /path/to/project --memory 8G --git-mode ro
   ```

---

## Options & Configuration

| Option / Flag | Environment Variable | Description | Default Value | Possible Values |
| :--- | :--- | :--- | :--- | :--- |
| `project_dir` | N/A | Path to the target project directory to mount | *(Required)* | Any valid directory path |
| `--git-mode` | `ACLI_GIT_MODE` / `ACLI_GIT_PROTECTION` | Git repository protection mode | `ro` | `ro`, `tmpfs`, `rw` |
| `--git-hooks-mode` | `ACLI_GIT_HOOKS_MODE` | Protection mode for `.git/hooks` | `ro` (or `tmpfs` if `git-mode=rw`) | `ro`, `tmpfs`, `rw` |
| `--workspace-protection` / `--no-workspace-protection` | `ACLI_WORKSPACE_PROTECTION` | Protect IDE run configs (`.vscode`, `.idea`) & `.envrc` as read-only | `true` (`--workspace-protection`) | `true`, `false` |
| `--mask-env` / `--no-mask-env` | `ACLI_MASK_ENV` | Mask `.env*` files as 0-byte empty files | `true` (`--mask-env`) | `true`, `false` |
| `--tools-ro` / `--no-tools-ro` | `ACLI_TOOLS_RO` | Mount tool configuration root directories as read-only | `true` (`--tools-ro`) | `true`, `false` |
| `--persistence` | `ACLI_PERSISTENCE` | Session state and persistence storage scoping | `per-project` | `per-project`, `global` |
| `--tools` | `ACLI_TOOLS` | Comma-separated agent CLI tool profiles to mount | `copilot,vibe,antigravity` | Any combination of `copilot`, `vibe`, `antigravity` |
| `--memory` | `ACLI_MEMORY` | Container memory limit | `16G` | E.g., `4G`, `8G`, `16G`, `32G` |

---

## Usage Examples

- **Standard Run (Default Protections):**
  ```bash
  uv run acli ~/projects/my-app
  ```

- **Allowing Git Writes while Sandboxing Hooks:**
  ```bash
  uv run acli . --git-mode rw --git-hooks-mode tmpfs
  ```

- **Running with specific tools & reduced memory:**
  ```bash
  uv run acli . --tools vibe,antigravity --memory 8G
  ```
