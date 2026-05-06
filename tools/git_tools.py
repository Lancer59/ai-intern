"""
Git tools for AI Intern.

Gives the agent full version control awareness:
  - Clone a remote repo into the workspace
  - Read status, diff, log, blame
  - Commit, branch, checkout, push, pull, stash
  - AI-assisted commit message generation (reads staged diff)

All tools use asyncio.to_thread since GitPython is synchronous.
Destructive tools (commit, push, pull, checkout) should be added to
approval_tools in coding_assistant.py to trigger the human-in-the-loop
interrupt in the Chainlit UI.
"""

import asyncio
import json
import logging
import os
from datetime import datetime

from git import GitCommandError, InvalidGitRepositoryError, Repo
from langchain_core.tools import tool

logger = logging.getLogger("git_tools")

_MAX_DIFF_CHARS = 20_000


def _repo(path: str) -> Repo:
    """Open a Repo, raising a clean ValueError if the path isn't a git repo."""
    try:
        return Repo(path, search_parent_directories=False)
    except InvalidGitRepositoryError:
        raise ValueError(f"Not a git repository: {path}")


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------

@tool
async def git_clone(remote_url: str, destination: str = "", parent_dir: str = "") -> str:
    """Clone a remote Git repository into the workspace so the agent can work on it.

    The repo is cloned as a sibling of the ai-intern folder (same parent directory).
    Will not overwrite an existing folder.

    :param remote_url: HTTPS or SSH URL of the remote repo (e.g. 'https://github.com/user/repo.git').
    :param destination: Optional folder name for the clone. Defaults to the repo name from the URL.
    :param parent_dir: Optional absolute path to clone into. Defaults to the parent of the current working directory.
    :return: Absolute path of the cloned repo, or an error message.
    """
    def _run():
        # Resolve destination folder name
        folder = destination.strip() if destination.strip() else remote_url.rstrip("/").split("/")[-1].removesuffix(".git")

        # Resolve parent directory
        base = parent_dir.strip() if parent_dir.strip() else os.path.dirname(os.path.abspath(__file__))
        # Go one level up so the clone lands next to ai-intern, not inside it
        clone_root = os.path.dirname(base) if os.path.basename(base) == os.path.basename(os.path.abspath(__file__)) else base

        target = os.path.join(clone_root, folder)
        if os.path.exists(target):
            return f"Error: Destination already exists: {target}. Choose a different folder name."

        try:
            Repo.clone_from(remote_url, target)
            return f"Cloned '{remote_url}' → {target}"
        except GitCommandError as e:
            return f"Error: git clone failed: {e.stderr.strip()}"

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------

@tool
async def git_status(repo_path: str) -> str:
    """Return the working tree status of a git repository.

    Shows staged, modified, and untracked files.

    :param repo_path: Absolute or relative path to the git repository root.
    :return: Formatted status string, or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        staged = [item.a_path for item in repo.index.diff("HEAD")] if repo.head.is_valid() else []
        modified = [item.a_path for item in repo.index.diff(None)]
        untracked = repo.untracked_files
        branch = repo.active_branch.name if not repo.head.is_detached else "HEAD (detached)"
        lines = [f"Branch: {branch}"]
        lines.append(f"Staged ({len(staged)}): {', '.join(staged) or 'none'}")
        lines.append(f"Modified ({len(modified)}): {', '.join(modified) or 'none'}")
        lines.append(f"Untracked ({len(untracked)}): {', '.join(untracked) or 'none'}")
        return "\n".join(lines)

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


@tool
async def git_diff(repo_path: str, file_path: str = "", staged: bool = False) -> str:
    """Return the unified diff of the working directory or a specific file.

    :param repo_path: Path to the git repository root.
    :param file_path: Optional path to a specific file. Diffs all changes if omitted.
    :param staged: If True, returns the diff of staged (index) changes only.
    :return: Unified diff string (truncated at 20,000 chars), or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        kwargs = {"create_patch": True}
        if file_path:
            kwargs["paths"] = [file_path]

        if staged:
            diffs = repo.index.diff("HEAD", **kwargs) if repo.head.is_valid() else []
        else:
            diffs = repo.index.diff(None, **kwargs)

        parts = []
        for d in diffs:
            try:
                parts.append(d.diff.decode("utf-8", errors="replace"))
            except Exception:
                parts.append(str(d))

        result = "\n".join(parts) or "No changes."
        if len(result) > _MAX_DIFF_CHARS:
            result = result[:_MAX_DIFF_CHARS] + f"\n\n... [truncated at {_MAX_DIFF_CHARS} characters]"
        return result

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


@tool
async def git_log(repo_path: str, max_count: int = 10, file_path: str = "") -> str:
    """Return recent commit history as a JSON array.

    :param repo_path: Path to the git repository root.
    :param max_count: Number of commits to return (default 10).
    :param file_path: Optional file path to scope the log to one file.
    :return: JSON array of {hash, author, date, message} objects, or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        kwargs = {"max_count": max_count}
        if file_path:
            kwargs["paths"] = [file_path]
        commits = []
        for c in repo.iter_commits(**kwargs):
            commits.append({
                "hash": c.hexsha[:8],
                "author": f"{c.author.name} <{c.author.email}>",
                "date": datetime.fromtimestamp(c.committed_date).strftime("%Y-%m-%d %H:%M"),
                "message": c.message.strip(),
            })
        return json.dumps(commits, indent=2)

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


@tool
async def git_blame(repo_path: str, file_path: str, start_line: int = 0, end_line: int = 0) -> str:
    """Return line-by-line authorship for a file.

    :param repo_path: Path to the git repository root.
    :param file_path: Path to the file (relative to repo root).
    :param start_line: First line to include (1-indexed, 0 = from beginning).
    :param end_line: Last line to include (0 = to end of file).
    :return: Formatted blame string, or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        blame = repo.blame("HEAD", file_path)
        lines_out = []
        line_num = 1
        for commit, lines in blame:
            for line in lines:
                if (start_line == 0 or line_num >= start_line) and (end_line == 0 or line_num <= end_line):
                    text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
                    lines_out.append(
                        f"{commit.hexsha[:8]} {commit.author.name:<20} "
                        f"{datetime.fromtimestamp(commit.committed_date).strftime('%Y-%m-%d')} "
                        f"L{line_num:>4}: {text.rstrip()}"
                    )
                line_num += 1
        return "\n".join(lines_out) or "No blame data."

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------

@tool
async def git_commit(repo_path: str, message: str, files: list = None) -> str:
    """Stage files and create a commit.

    Stages all changes if no files are specified.
    Never amends or force-pushes.

    :param repo_path: Path to the git repository root.
    :param message: Commit message (must be non-empty).
    :param files: Optional list of file paths to stage. Stages everything if omitted.
    :return: Commit hash and summary, or an error message.
    """
    def _run():
        if not message.strip():
            return "Error: Commit message cannot be empty."
        repo = _repo(repo_path)
        if files:
            repo.index.add(files)
        else:
            repo.git.add(A=True)
        commit = repo.index.commit(message.strip())
        return f"Committed {commit.hexsha[:8]}: {commit.message.strip()}"

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


@tool
async def git_create_branch(repo_path: str, branch_name: str) -> str:
    """Create and check out a new branch.

    Use this before making a series of risky changes (safe experimentation mode).

    :param repo_path: Path to the git repository root.
    :param branch_name: Name for the new branch.
    :return: Confirmation string, or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()
        return f"Created and checked out branch: {branch_name}"

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


@tool
async def git_checkout(repo_path: str, target: str) -> str:
    """Switch to an existing branch or restore a file to HEAD.

    :param repo_path: Path to the git repository root.
    :param target: Branch name to switch to, or a file path to restore.
    :return: Confirmation string, or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        # If target looks like a file path, restore it
        full_path = os.path.join(repo_path, target)
        if os.path.exists(full_path) and not os.path.isdir(full_path):
            repo.git.checkout("HEAD", "--", target)
            return f"Restored file to HEAD: {target}"
        # Otherwise treat as branch name
        repo.git.checkout(target)
        return f"Switched to branch: {target}"

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


@tool
async def git_push(repo_path: str, remote: str = "origin", branch: str = "") -> str:
    """Push the current branch to a remote. Never force-pushes.

    :param repo_path: Path to the git repository root.
    :param remote: Remote name (default 'origin').
    :param branch: Branch to push. Defaults to the current active branch.
    :return: Push result summary, or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        target_branch = branch.strip() if branch.strip() else repo.active_branch.name
        push_info = repo.remotes[remote].push(refspec=f"{target_branch}:{target_branch}")
        results = []
        for info in push_info:
            results.append(f"{info.remote_ref_string}: {info.summary.strip()}")
        return "\n".join(results) or f"Pushed {target_branch} → {remote}"

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


@tool
async def git_pull(repo_path: str, remote: str = "origin") -> str:
    """Pull latest changes from remote into the current branch.

    :param repo_path: Path to the git repository root.
    :param remote: Remote name (default 'origin').
    :return: Pull result summary, or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        result = repo.remotes[remote].pull()
        summaries = [info.note.strip() or "ok" for info in result]
        return f"Pulled from {remote}: {', '.join(summaries)}"

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


@tool
async def git_stash(repo_path: str, action: str = "push", message: str = "") -> str:
    """Stash or restore uncommitted changes.

    :param repo_path: Path to the git repository root.
    :param action: 'push' to stash changes, 'pop' to restore the latest stash.
    :param message: Optional label when pushing a stash.
    :return: Confirmation string, or an error message.
    """
    def _run():
        repo = _repo(repo_path)
        if action == "push":
            args = ["push"]
            if message.strip():
                args += ["-m", message.strip()]
            repo.git.stash(*args)
            return f"Stashed changes{f': {message}' if message.strip() else ''}."
        elif action == "pop":
            repo.git.stash("pop")
            return "Restored latest stash."
        else:
            return f"Error: Unknown action '{action}'. Use 'push' or 'pop'."

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# AI-assisted
# ---------------------------------------------------------------------------

@tool
async def git_generate_commit_message(repo_path: str) -> str:
    """Read the staged diff and return a suggested conventional-commits message.

    This tool reads the staged diff and returns it formatted as a prompt
    for the agent to generate a commit message. The agent should call
    git_commit with the generated message afterwards.

    :param repo_path: Path to the git repository root.
    :return: The staged diff with instructions to generate a commit message.
    """
    def _run():
        repo = _repo(repo_path)
        diffs = repo.index.diff("HEAD", create_patch=True) if repo.head.is_valid() else []
        parts = []
        for d in diffs:
            try:
                parts.append(d.diff.decode("utf-8", errors="replace"))
            except Exception:
                parts.append(str(d))
        diff_text = "\n".join(parts) or "No staged changes found."
        if len(diff_text) > _MAX_DIFF_CHARS:
            diff_text = diff_text[:_MAX_DIFF_CHARS] + "\n... [truncated]"
        return (
            "Staged diff:\n\n"
            f"{diff_text}\n\n"
            "Based on the diff above, write a concise conventional-commits style commit message "
            "(e.g. 'feat: add login validation' or 'fix: resolve null pointer in auth handler'). "
            "One subject line only, under 72 characters."
        )

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return f"Error: {e}"
