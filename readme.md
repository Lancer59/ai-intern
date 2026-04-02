# AI Intern — AI-Powered Coding Assistant

A terminal & web-based AI coding assistant built on the [deepagents](https://github.com/langchain-ai/deepagents) library. It can explore, plan, and modify code in any local repository through a modern chat interface.

---

## Features

- **Multi-Provider LLM Support** — Azure OpenAI, OpenAI, Google Gemini, and local Ollama models via a unified factory.
- **Deep Agent** — Powered by `deepagents` with built-in planning (`write_todos`), filesystem tools (`ls`, `read_file`, `write_file`, `edit_file`, `grep`, `glob`), shell execution, and sub-agent spawning.
- **Model Context Protocol (MCP)** — Native integration via `langchain_mcp_adapters` to connect standard MCP servers (e.g., Microsoft Docs) for extended context.
- **Custom Tooling Extensibility** — Includes robust custom tools (such as `think` for deep reasoning) loaded directly into the agent mapping.
- **Chainlit Web UI** — Real-time token streaming, custom aesthetic tool step indicators ("Editing...", "Thinking..."), inline visual Diff and Terminal blocks, and a dynamic **Tasks** sidebar.
- **In-Memory Persistence** — Conversation memory is maintained across turns within a session via LangGraph's `MemorySaver` checkpointer with unique `thread_id`s.
- **CLI Mode** — Lightweight terminal interface for quick interactions.

---

## Project Structure

```
ai-intern/
├── llm_factory.py           # Multi-provider LLM initialization
├── coding_assistant.py      # DeepAgent configuration & system prompt
├── mcp_client.py            # Model Context Protocol server configuration
├── tools.py                 # Custom Langchain tools (e.g., think)
├── assistant_ui.py          # Chainlit web UI (main entry point)
├── assistant_cli.py         # CLI interface (alternative)
├── .env.example             # Template for API keys
├── requirements-simple.txt  # Core dependencies
├── requirements.txt         # Full pip freeze
├── architecture.md          # Architectural overview, diagram, and usecases 
└── readme.md
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone <repo-url>
cd ai-intern
python -m venv env
env\Scripts\activate        # Windows
pip install -r requirements-simple.txt
```

### 2. Configure API Keys

```bash
cp .env.example .env
# Edit .env with your actual API keys
```

### 3. Run the Web UI

```bash
# First time only — create the Chainlit SQLite schema
python init_db.py

chainlit run assistant_ui.py
```

Open [http://localhost:8000](http://localhost:8000) and enter the name of a sibling project folder (e.g., `my-project`). The assistant will have full access to that repository.

### 4. (Alternative) Run the CLI

```bash
python assistant_cli.py
```

---

## How It Works

1. **You provide a project folder name** — the assistant maps it to a sibling directory alongside `ai-intern/`.
2. **The agent plans first** — it uses `write_todos` to create a task list before touching any code.
3. **It explores efficiently** — `grep` and `glob` find files & line numbers directly instead of navigating with `ls`.
4. **It streams results in real-time** — tokens appear word-by-word, tool calls show as collapsible steps, and the task sidebar updates live.
5. **Memory persists across turns** — within a session, the agent remembers everything you've discussed.

---

## Configuration

### Switching LLM Providers

Edit the provider in `coding_assistant.py`:

```python
llm = get_llm(provider="azure")      # Azure OpenAI (default)
llm = get_llm(provider="openai")     # OpenAI
llm = get_llm(provider="google")     # Google Gemini
llm = get_llm(provider="ollama")     # Local Ollama
```

### Persistent Memory (Production)

Conversation history and agent state are persisted to SQLite automatically:
- `agent_data/chainlit_ui.db` — Chainlit UI threads, messages, history sidebar
- `agent_data/checkpoints_lg.db` — LangGraph agent state (tool calls, messages per thread)
- `/memories/` — Cross-session long-term memory via deepagents `StoreBackend` (agent writes here to remember things across conversations)

To use PostgreSQL in production, swap `SQLAlchemyDataLayer` conninfo and `AsyncSqliteSaver` for their Postgres equivalents.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `AZURE_OPENAI_API_KEY` | For Azure | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | For Azure | Azure resource endpoint |
| `AZURE_OPENAI_API_VERSION` | For Azure | API version |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | For Azure | Model deployment name |
| `OPENAI_API_KEY` | For OpenAI | OpenAI API key |
| `GOOGLE_API_KEY` | For Google | Google Gemini API key |
| `TAVILY_API_KEY` | For MCP | Tavily web search API key |
| `CHAINLIT_AUTH_SECRET` | Yes | Secret for Chainlit cookie auth |
| `CHAINLIT_USER` | Yes | Login username |
| `CHAINLIT_PASSWORD` | Yes | Login password |

---

## ToDO

- [ ] Docker-based sandboxed execution
- [ ] Project-level `AGENTS.md` for persistent context
- [ ] Agent skills which can be added dynamically
- [ ] Set iteration limit dynamically for each query
- [ ] git tools so the coding agent can push code
- [ ] Swap SQLite for PostgreSQL for multi-user production deployments
- [ ] checkpointer in conversation 
- [ ] No git tooling, no .ai-intern-rules project context file, no semantic repo map
- [ ] See content from python files of packages within the code base
- [ ] Trust command (user based auth)
- [ ] Unable to replace text trying different approach
- [ ] Optimized for building requirements and technical documentation 
---

## License

MIT