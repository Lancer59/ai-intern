# AI Intern — AI-Powered Coding Assistant

A web-based AI coding assistant built on [deepagents](https://github.com/langchain-ai/deepagents). It can explore, plan, and modify code in any local repository through this chat interface.

---

## Getting Started

Enter the name of a **sibling project folder** (e.g. `my-project`) when prompted. The assistant will map it to the directory alongside `ai-intern/` and have full access to that repository.

---

## What it can do

- **Plan first** — uses `write_todos` to create a task list before touching any code
- **Explore efficiently** — `grep` and `glob` find files & line numbers directly
- **Stream results in real-time** — tokens appear word-by-word, tool calls show as collapsible steps, and the task sidebar updates live
- **Remember across turns** — within a session the agent remembers everything discussed
- **Long-term memory** — saves project context to `/memories/context.md` across sessions
- **Shell execution** — runs commands with approval prompts for destructive operations
- **MCP tools** — Microsoft Docs, Tavily search, DeepWiki, and more

---

## LLM Providers supported

Azure OpenAI · OpenAI · Google Gemini · Ollama (local)

---

## 📊 [Open Dashboard →](/dashboard)

View observability metrics (token usage, tool stats, lines of code written) and edit agent settings (iteration limit, system prompt, allowed tools) from the combined dashboard.

> [!NOTE]
> The dashboard is only available when running the application via `uvicorn app:app`. If running via `chainlit run`, this link will redirect back to the chat.

---

## Persistent storage

| File | Purpose |
|---|---|
| `agent_data/chainlit_ui.db` | Chat threads & message history |
| `agent_data/checkpoints_lg.db` | LangGraph agent state per thread |
| `agent_data/dashboard.db` | Telemetry & agent config |
| `/memories/` | Cross-session long-term memory |
