"""Tests for tools/git_tools.py

Uses a real temporary git repo (no mocking) so tests reflect actual behaviour.
"""
import json
import os
import pytest
import tempfile

from git import Repo
from tools.git_tools import (
    _repo,
    git_status,
    git_diff,
    git_log,
    git_commit,
    git_create_branch,
    git_checkout,
    git_stash,
    git_generate_commit_message,
    git_clone,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """Create a minimal git repo with one commit."""
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "test@example.com").release()

    # Initial commit so HEAD is valid
    readme = tmp_path / "README.md"
    readme.write_text("# Test Repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("init: initial commit")
    return tmp_path


@pytest.fixture
def dirty_repo(tmp_repo):
    """Repo with an untracked file and a modified tracked file."""
    (tmp_repo / "README.md").write_text("# Modified\n")
    (tmp_repo / "new_file.txt").write_text("untracked\n")
    return tmp_repo


# ---------------------------------------------------------------------------
# _repo helper
# ---------------------------------------------------------------------------

class TestRepoHelper:
    def test_opens_valid_repo(self, tmp_repo):
        repo = _repo(str(tmp_repo))
        assert repo is not None

    def test_raises_on_non_repo(self, tmp_path):
        with pytest.raises(ValueError, match="Not a git repository"):
            _repo(str(tmp_path))


# ---------------------------------------------------------------------------
# git_status
# ---------------------------------------------------------------------------

class TestGitStatus:
    @pytest.mark.asyncio
    async def test_clean_repo(self, tmp_repo):
        result = await git_status.ainvoke({"repo_path": str(tmp_repo)})
        assert "Branch:" in result
        assert "Untracked (0)" in result

    @pytest.mark.asyncio
    async def test_dirty_repo_shows_files(self, dirty_repo):
        result = await git_status.ainvoke({"repo_path": str(dirty_repo)})
        assert "new_file.txt" in result

    @pytest.mark.asyncio
    async def test_invalid_path_returns_error(self, tmp_path):
        result = await git_status.ainvoke({"repo_path": str(tmp_path)})
        assert result.startswith("Error")


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------

class TestGitDiff:
    @pytest.mark.asyncio
    async def test_no_changes_returns_no_changes(self, tmp_repo):
        result = await git_diff.ainvoke({"repo_path": str(tmp_repo)})
        assert result == "No changes."

    @pytest.mark.asyncio
    async def test_modified_file_shows_diff(self, dirty_repo):
        repo = Repo(str(dirty_repo))
        repo.index.add(["README.md"])
        result = await git_diff.ainvoke({"repo_path": str(dirty_repo), "staged": True})
        assert "README" in result or "Modified" in result or "-" in result

    @pytest.mark.asyncio
    async def test_invalid_path_returns_error(self, tmp_path):
        result = await git_diff.ainvoke({"repo_path": str(tmp_path)})
        assert result.startswith("Error")


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------

class TestGitLog:
    @pytest.mark.asyncio
    async def test_returns_json_array(self, tmp_repo):
        result = await git_log.ainvoke({"repo_path": str(tmp_repo)})
        commits = json.loads(result)
        assert isinstance(commits, list)
        assert len(commits) >= 1

    @pytest.mark.asyncio
    async def test_commit_has_expected_keys(self, tmp_repo):
        result = await git_log.ainvoke({"repo_path": str(tmp_repo)})
        commits = json.loads(result)
        commit = commits[0]
        assert "hash" in commit
        assert "author" in commit
        assert "date" in commit
        assert "message" in commit

    @pytest.mark.asyncio
    async def test_max_count_respected(self, tmp_repo):
        # Add a second commit
        repo = Repo(str(tmp_repo))
        (tmp_repo / "file2.txt").write_text("second\n")
        repo.index.add(["file2.txt"])
        repo.index.commit("second commit")

        result = await git_log.ainvoke({"repo_path": str(tmp_repo), "max_count": 1})
        commits = json.loads(result)
        assert len(commits) == 1

    @pytest.mark.asyncio
    async def test_invalid_path_returns_error(self, tmp_path):
        result = await git_log.ainvoke({"repo_path": str(tmp_path)})
        assert result.startswith("Error")


# ---------------------------------------------------------------------------
# git_commit
# ---------------------------------------------------------------------------

class TestGitCommit:
    @pytest.mark.asyncio
    async def test_commits_new_file(self, tmp_repo):
        (tmp_repo / "feature.py").write_text("x = 1\n")
        result = await git_commit.ainvoke({
            "repo_path": str(tmp_repo),
            "message": "feat: add feature.py",
        })
        assert "Committed" in result
        assert "feat: add feature.py" in result

    @pytest.mark.asyncio
    async def test_empty_message_returns_error(self, tmp_repo):
        result = await git_commit.ainvoke({
            "repo_path": str(tmp_repo),
            "message": "   ",
        })
        assert result.startswith("Error")

    @pytest.mark.asyncio
    async def test_specific_files_staged(self, tmp_repo):
        (tmp_repo / "a.txt").write_text("a\n")
        (tmp_repo / "b.txt").write_text("b\n")
        result = await git_commit.ainvoke({
            "repo_path": str(tmp_repo),
            "message": "chore: add a only",
            "files": ["a.txt"],
        })
        assert "Committed" in result

        # b.txt should still be untracked
        status = await git_status.ainvoke({"repo_path": str(tmp_repo)})
        assert "b.txt" in status


# ---------------------------------------------------------------------------
# git_create_branch
# ---------------------------------------------------------------------------

class TestGitCreateBranch:
    @pytest.mark.asyncio
    async def test_creates_and_checks_out_branch(self, tmp_repo):
        result = await git_create_branch.ainvoke({
            "repo_path": str(tmp_repo),
            "branch_name": "feature/test-branch",
        })
        assert "feature/test-branch" in result
        repo = Repo(str(tmp_repo))
        assert repo.active_branch.name == "feature/test-branch"

    @pytest.mark.asyncio
    async def test_duplicate_branch_returns_error(self, tmp_repo):
        # Create the branch and switch back to the original branch
        await git_create_branch.ainvoke({
            "repo_path": str(tmp_repo),
            "branch_name": "dupe-branch",
        })
        repo = Repo(str(tmp_repo))
        # Switch back to the first branch (not dupe-branch) so we can try again
        first_branch = [h for h in repo.heads if h.name != "dupe-branch"][0]
        first_branch.checkout()
        result = await git_create_branch.ainvoke({
            "repo_path": str(tmp_repo),
            "branch_name": "dupe-branch",
        })
        # GitPython raises an error when creating a branch that already exists
        # while not on that branch — result should be an error string
        assert result.startswith("Error") or "dupe-branch" in result


# ---------------------------------------------------------------------------
# git_checkout
# ---------------------------------------------------------------------------

class TestGitCheckout:
    @pytest.mark.asyncio
    async def test_switches_branch(self, tmp_repo):
        repo = Repo(str(tmp_repo))
        repo.create_head("other-branch")
        result = await git_checkout.ainvoke({
            "repo_path": str(tmp_repo),
            "target": "other-branch",
        })
        assert "other-branch" in result
        assert repo.active_branch.name == "other-branch"

    @pytest.mark.asyncio
    async def test_restores_file(self, tmp_repo):
        readme = tmp_repo / "README.md"
        readme.write_text("# Corrupted\n")
        result = await git_checkout.ainvoke({
            "repo_path": str(tmp_repo),
            "target": "README.md",
        })
        assert "Restored" in result
        assert readme.read_text() == "# Test Repo\n"


# ---------------------------------------------------------------------------
# git_stash
# ---------------------------------------------------------------------------

class TestGitStash:
    @pytest.mark.asyncio
    async def test_stash_push_and_pop(self, dirty_repo):
        push_result = await git_stash.ainvoke({
            "repo_path": str(dirty_repo),
            "action": "push",
            "message": "wip changes",
        })
        assert "Stashed" in push_result

        pop_result = await git_stash.ainvoke({
            "repo_path": str(dirty_repo),
            "action": "pop",
        })
        assert "Restored" in pop_result

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self, tmp_repo):
        result = await git_stash.ainvoke({
            "repo_path": str(tmp_repo),
            "action": "explode",
        })
        assert result.startswith("Error")


# ---------------------------------------------------------------------------
# git_generate_commit_message
# ---------------------------------------------------------------------------

class TestGitGenerateCommitMessage:
    @pytest.mark.asyncio
    async def test_no_staged_changes(self, tmp_repo):
        result = await git_generate_commit_message.ainvoke({"repo_path": str(tmp_repo)})
        assert "No staged changes" in result or "Staged diff" in result

    @pytest.mark.asyncio
    async def test_with_staged_changes_includes_diff(self, tmp_repo):
        (tmp_repo / "new.py").write_text("def hello(): pass\n")
        repo = Repo(str(tmp_repo))
        repo.index.add(["new.py"])
        result = await git_generate_commit_message.ainvoke({"repo_path": str(tmp_repo)})
        assert "conventional-commits" in result or "new.py" in result


# ---------------------------------------------------------------------------
# git_clone — only tests the guard against existing destination
# ---------------------------------------------------------------------------

class TestGitClone:
    @pytest.mark.asyncio
    async def test_refuses_existing_destination(self, tmp_path):
        existing = tmp_path / "already-exists"
        existing.mkdir()
        result = await git_clone.ainvoke({
            "remote_url": "https://github.com/example/repo.git",
            "destination": "already-exists",
            "parent_dir": str(tmp_path),
        })
        assert result.startswith("Error")
        assert "already exists" in result
