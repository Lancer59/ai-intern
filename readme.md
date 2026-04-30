# AI Intern — AI-Powered Coding Assistant

A terminal & web-based AI coding assistant built on the [deepagents](https://github.com/langchain-ai/deepagents) library. It can explore, plan, and modify code in any local repository through a modern chat interface.

---

## Features

- **Multi-Provider LLM Support** — Azure OpenAI, OpenAI, Google Gemini, and local Ollama models via a unified factory.
- **Deep Agent** — Powered by `deepagents` with built-in planning (`write_todos`), filesystem tools (`ls`, `read_file`, `write_file`, `edit_file`, `grep`, `glob`), shell execution, and sub-agent spawning.
- **Model Context Protocol (MCP)** — Native integration via `langchain_mcp_adapters` to connect standard MCP servers (e.g., Microsoft Docs) for extended context.
- **Custom Tooling Extensibility** — Includes robust custom tools (such as `think` for deep reasoning) loaded directly into the agent mapping.
- **Browser Interaction (Playwright + Edge)** — Five built-in browser tools let the agent visually verify frontend work: take screenshots, capture JS console logs, read the DOM, click elements, and detect failed network requests — all driven headlessly through your installed Microsoft Edge.
- **Chainlit Web UI** — Real-time token streaming, custom aesthetic tool step indicators ("Editing...", "Thinking..."), inline visual Diff and Terminal blocks, and a dynamic **Tasks** sidebar.
- **Admin Dashboard** — Integrated FastAPI dashboard for observability (token usage, tool stats, LOC) and real-time agent configuration (system prompt, iteration limits).
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
├── browser_tools.py         # Playwright browser tools (screenshot, DOM, console, network)
├── assistant_ui.py          # Chainlit web UI
├── dashboard/               # Dashboard frontend (React/HTML)
├── dashboard_api.py         # Dashboard FastAPI backend
├── dashboard_db.py          # Dashboard database logic
├── app.py                   # Combined production entry point (Chat + Dashboard)
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
# First time only — create the SQLite schemas
python init_db.py

# Run the combined app (Chat at / and Dashboard at /dashboard)
uvicorn app:app --host 127.0.0.1 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) and enter the name of a sibling project folder (e.g., `my-project`). The assistant will have full access to that repository.

### 4. (Alternative) Run the CLI

```bash
python assistant_cli.py
```

---

## Admin Dashboard

The project includes a built-in dashboard for monitoring and configuration:

- **Observability**: Track token usage (prompt vs completion), model distribution, and tool invocation stats.
- **Agent Configuration**: Edit the system prompt, iteration limits, and toggle specific tools on/off in real-time.
- **Session History**: View detailed logs of past conversations, including exact tool calls and durations.

Access it at [http://localhost:8000/dashboard](http://localhost:8000/dashboard) when running via `app.py`.

---

## Browser Interaction Tools

The agent can interact with a running browser to verify frontend changes without any manual DevTools work. All tools are powered by Playwright and use your system-installed **Microsoft Edge** — no extra browser download needed.

| Tool | What it does |
|------|-------------|
| `browser_screenshot` | Navigates to a URL and returns a screenshot rendered inline in the chat |
| `browser_get_console_logs` | Captures all `console.error`, `console.warn`, and `console.log` output during page load |
| `browser_get_dom` | Returns the `outerHTML` of a CSS selector or the full `body.innerHTML` |
| `browser_click_and_screenshot` | Clicks an element by CSS selector and screenshots the resulting state |
| `browser_get_network_errors` | Lists all HTTP 4xx/5xx responses and failed requests during page load |

**Setup** — just install the Python package, no browser binary download required (If you have MS Edge, else download is required.):

```bash
pip install playwright
# playwright install msedge  ← only if Edge isn't already on your machine
```

**External URL access** — by default all tools allow navigation to any URL including cloud/public sites. To restrict to `localhost` only (e.g. for a sandboxed environment), pass `allow_external=False` when calling any browser tool, or flip the default in `browser_tools.py`:

```python
# browser_tools.py — change the default on any tool signature
async def browser_screenshot(url: str, ..., allow_external: bool = False):  # locked to localhost
async def browser_screenshot(url: str, ..., allow_external: bool = True):   # allows all URLs (default)
```

**Self-healing loop example** — the agent can chain these tools automatically:

```
edit_file → execute (npm run dev) → browser_screenshot
         → browser_get_console_logs → [errors found] → think → edit_file → ...
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
- [ ] Git tooling
- [ ] See content from python files of packages within the code base
- [ ] Trust command (user based auth)
- [ ] Unable to replace text trying different approach
- [ ] Optimized for building requirements and technical documentation 
- [ ] Extend configurability (Ex: add edge/chrome option for playwright)
---

## License

MIT