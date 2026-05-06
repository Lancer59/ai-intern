# AI Intern: Developer Experience Improvement Suggestions

Based on an analysis of current market leaders in AI-assisted development (such as Cursor, Aider, Cline/Claude Dev, and GitHub Copilot), here is a structured list of improvements to make **AI Intern** significantly more useful, powerful, and seamless for developers.

---

## ✅ 1. Deep Context & Codebase Understanding (Inspired by Cursor & Aider)
**Status: Fully implemented**

*   **✅ Semantic Repository Map:** A lightweight file-tree based repo map is generated at session start and injected into the system prompt (`_build_repo_map` in `core/coding_assistant.py`). The agent knows the full file structure without needing to manually `ls`.
*   **✅ Vector Search Navigation:** Implemented in `tools/vector_search.py`. Two tools added: `semantic_code_search` (find code by concept — "Where is the auth logic?") and `rebuild_code_index` (force re-index after large refactors). Uses ChromaDB with a persistent index in `agent_data/chroma/`. Embeddings use Ollama (`nomic-embed-text`) locally with automatic fallback to OpenAI `text-embedding-3-small`.

---

## ⬜ 2. Granular, Diff-based File Editing (Inspired by Aider)
**Status: Not implemented**

Replacing entire files or using naive string replacement becomes fragile and expensive (token-wise) on files containing hundreds of lines.

*   **Search/Replace Blocks:** Implement a tool similar to Aider's `SEARCH/REPLACE` blocks. The AI outputs only the chunk of code being changed, preceded by the exact existing lines.
*   **Unified Diff Output:** Allow the AI to output unified diffs that the backend applies locally. This drastically speeds up execution and prevents LLM truncation on large files.

---

## ✅ 3. Autonomous Execution & Self-Healing (Inspired by Cline)
**Status: Implemented**

*   **✅ Auto-Linting & Test Loops:** The agent can already run linters and tests via the `execute` tool, capture stderr/stdout, and iterate until the exit code is 0. This is part of the core agent loop.
*   **✅ Browser Interaction:** Fully implemented in `tools/browser_tools.py` via Playwright + MS Edge. The agent can take screenshots, capture JS console logs, read the DOM, click elements, and detect failed network requests — all headlessly. Supports any URL (localhost or external). Screenshots render inline in the Chainlit UI.

---

## ⬜ 4. IDE Integration or Editor Proximity (Inspired by Cursor/Copilot)
**Status: Not implemented**

While Chainlit provides a beautiful UI, switching contexts between an IDE and a browser breaks developer flow.

*   **VS Code / JetBrains Plugin:** Expose a local REST/WebSocket API from the AI Intern core and build a lightweight VS Code extension. This allows the AI to see the developer's exact cursor position, open tabs, and selected text.
*   **Inline Code Completion:** Offer rapid, local autocomplete for inline suggestions (perhaps leveraging the existing Ollama integration) while reserving the complex reasoning API for the chat pane.

---

## ✅ 5. Advanced Version Control (Git) Integrations
**Status: Implemented**

Fully implemented in `tools/git_tools.py` via GitPython. 12 tools covering the complete Git lifecycle:

*   **✅ Clone from remote URL:** `git_clone` — share any GitHub/GitLab URL and the agent clones it directly into the workspace.
*   **✅ Contextual Commits:** `git_generate_commit_message` reads the staged diff and generates a conventional-commits style message. `git_commit` stages and commits.
*   **✅ Safe Experimentation Mode:** `git_create_branch` lets the agent branch before risky changes. If the result is unwanted, the branch is discarded with no impact on `main`.
*   **✅ Full read/write coverage:** `git_status`, `git_diff`, `git_log`, `git_blame`, `git_checkout`, `git_push`, `git_pull`, `git_stash`.
*   **✅ Approval gates:** Destructive tools (`git_commit`, `git_push`, `git_pull`, `git_checkout`) trigger the human-in-the-loop interrupt in the Chainlit UI before executing.

---

## ✅ 6. Dynamic Context Loading (File Drag-and-Drop)
**Status: Implemented**

Developers can drag and drop images directly into the Chainlit chat UI. The agent receives them as base64-encoded image content and can reason about them using vision models. External URL fetching is available via MCP tools (Tavily, DeepWiki).

---

## ✅ 7. Configuration and Rules (Project-Level Memory)
**Status: Implemented**

*   **✅ `.ai-intern-rules` file:** Implemented in `core/coding_assistant.py` via `_read_ai_intern_rules`. Place a `.ai-intern-rules` markdown file at the root of any target repository and it is automatically prepended to the system context for all queries in that project. An example template is provided at `.ai-intern-rules.example`.

---

## ✅ 8. Codebase Structure & Organisation
**Status: Implemented**

The project has been restructured from a flat root into a clean module layout:

```
core/       ← coding_assistant.py, llm_factory.py, mcp_client.py
tools/      ← custom_tools.py, browser_tools.py, git_tools.py
dashboard/  ← api.py, db.py, static/
tests/      ← test_custom_tools.py, test_browser_tools.py, test_git_tools.py,
               test_dashboard_db.py, test_llm_factory.py
```

---

## ✅ 9. Test Coverage
**Status: Implemented**

57 pytest tests across 5 test files covering all major tool groups and the dashboard DB layer. Run with:

```bash
env/Scripts/pytest.exe tests/             # all non-browser tests (default)
env/Scripts/pytest.exe tests/ -m browser  # live browser tests (needs a running server)
```

---

## Remaining Roadmap

| Priority | Item | Notes |
|----------|------|-------|
| High | Diff-based file editing (Search/Replace blocks) | Biggest token savings, most impactful for large files |
| High | Vector search navigation (ChromaDB/FAISS) | Needed for large codebases where grep is too slow |
| Medium | VS Code / JetBrains plugin | Requires building a separate extension |
| Medium | Inline code completion (Ollama) | Needs a separate lightweight completion endpoint |
| Low | Docker-based sandboxed execution | Isolates agent shell commands from host machine |
| Low | PostgreSQL swap for multi-user deployments | SQLite is fine for single-user; Postgres needed for teams |
