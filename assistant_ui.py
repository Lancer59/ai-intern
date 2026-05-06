import chainlit as cl
import os
import asyncio
import logging
import uuid
import base64
import engineio
engineio.payload.Payload.max_decode_packets = 100000

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from core.coding_assistant import create_coding_assistant
from dashboard.db import init_db, get_config, record_llm_call, record_tool_invocation_start, record_tool_invocation_end, record_loc_event

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AssistantUI")

_db_initialized = False

# --- Persistence ---
@cl.data_layer
def get_data_layer():
    return SQLAlchemyDataLayer(conninfo="sqlite+aiosqlite:///agent_data/chainlit_ui.db")

# --- Auth ---
@cl.password_auth_callback
async def auth_callback(username: str, password: str):
    if username == os.getenv("CHAINLIT_USER", "admin") and password == os.getenv("CHAINLIT_PASSWORD", "admin"):
        user = cl.User(identifier=username, metadata={"role": "admin", "provider": "credentials"})
        # Ensure user exists in the DB so thread fetching works
        from chainlit.data import get_data_layer as _get_dl
        dl = _get_dl()
        if dl:
            existing = await dl.get_user(identifier=username)
            if not existing:
                await dl.create_user(user)
        return user
    return None

# --- LangGraph checkpointer (shared, persistent) ---
_checkpointer = None
_checkpointer_conn = None  # kept so lifespan in app.py can close it on shutdown
_store = InMemoryStore()

async def get_checkpointer():
    global _checkpointer, _checkpointer_conn
    if _checkpointer is None:
        import aiosqlite
        _checkpointer_conn = await aiosqlite.connect("agent_data/checkpoints_lg.db")
        _checkpointer = AsyncSqliteSaver(_checkpointer_conn)
        await _checkpointer.setup()
    return _checkpointer


@cl.on_chat_start
async def start():
    global _db_initialized
    if not _db_initialized:
        try:
            await init_db()
            _db_initialized = True
        except Exception as e:
            logger.warning(f"init_db failed: {e}")

    res = await cl.AskUserMessage(content="Enter the project folder name (sibling to ai-intern):").send()
    if not res:
        return

    project_folder = res['output'].strip()
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    workspace = os.path.abspath(os.path.join(parent_dir, project_folder))
    cl.user_session.set("workspace", workspace)

    try:
        msg = cl.Message(content="🏗️ Creating agents...")
        await msg.send()
        await asyncio.sleep(0.8)
        msg.content = "🔧 Loading tools into agent..."
        await msg.update()

        checkpointer = await get_checkpointer()
        user_id = cl.user_session.get("user").identifier if cl.user_session.get("user") else "default"
        try:
            agent_config = await get_config()
        except Exception as e:
            logger.warning(f"get_config failed, using defaults: {e}")
            agent_config = {}
        agent = await create_coding_assistant(
            workspace, checkpointer, _store, user_id=user_id,
            system_prompt=agent_config.get("system_prompt"),
            iteration_limit=agent_config.get("iteration_limit"),
            enabled_tools=agent_config.get("enabled_tools"),
            approval_tools=agent_config.get("approval_tools"),
        )
        thread_id = str(uuid.uuid4())

        cl.user_session.set("agent", agent)
        cl.user_session.set("thread_id", thread_id)

        # Persist thread_id + workspace in Chainlit thread metadata so on_chat_resume can reload them
        from chainlit.data import get_data_layer as _get_dl
        dl = _get_dl()
        if dl:
            await dl.update_thread(
                thread_id=cl.context.session.thread_id,
                metadata={"thread_id": thread_id, "workspace": workspace}
            )
        task_list = cl.TaskList()
        await task_list.send()
        cl.user_session.set("task_list", task_list)

        msg.content = f"🚀 AI Coding Assistant ready for: **{workspace}**"
        await msg.update()
    except Exception as e:
        await cl.Message(content=f"❌ Error initializing agent: {e}").send()


@cl.on_chat_resume
async def on_chat_resume(thread):
    global _db_initialized
    if not _db_initialized:
        try:
            await init_db()
            _db_initialized = True
        except Exception as e:
            logger.warning(f"init_db failed: {e}")

    import json
    raw_metadata = thread.get("metadata", {}) if isinstance(thread, dict) else {}
    if isinstance(raw_metadata, str):
        try:
            metadata = json.loads(raw_metadata)
        except Exception:
            metadata = {}
    else:
        metadata = raw_metadata or {}

    thread_id = metadata.get("thread_id")
    workspace = metadata.get("workspace", "")

    if not thread_id or not workspace:
        await cl.Message(content="⚠️ Could not restore session — missing metadata.").send()
        return

    try:
        checkpointer = await get_checkpointer()
        user_id = cl.user_session.get("user").identifier if cl.user_session.get("user") else "default"
        try:
            agent_config = await get_config()
        except Exception as e:
            logger.warning(f"get_config failed, using defaults: {e}")
            agent_config = {}
        agent = await create_coding_assistant(
            workspace, checkpointer, _store, user_id=user_id,
            system_prompt=agent_config.get("system_prompt"),
            iteration_limit=agent_config.get("iteration_limit"),
            enabled_tools=agent_config.get("enabled_tools"),
            approval_tools=agent_config.get("approval_tools"),
        )

        cl.user_session.set("agent", agent)
        cl.user_session.set("thread_id", thread_id)
        cl.user_session.set("workspace", workspace)

        task_list = cl.TaskList()
        await task_list.send()
        cl.user_session.set("task_list", task_list)

        logger.info(f"Resumed session thread_id={thread_id} workspace={workspace}")
    except Exception as e:
        await cl.Message(content=f"❌ Error resuming session: {e}").send()


@cl.on_message
async def main(message: cl.Message):
    agent = cl.user_session.get("agent")
    thread_id = cl.user_session.get("thread_id")

    if not agent:
        await cl.Message(content="Session expired or agent not ready. Please refresh.").send()
        return

    content = [{"type": "text", "text": message.content or ""}]
    for element in message.elements:
        if "image" in element.mime:
            image_data = element.content or (open(element.path, "rb").read() if element.path and os.path.exists(element.path) else None)
            if image_data:
                b64 = base64.b64encode(image_data).decode("utf-8")
                content.append({"type": "image_url", "image_url": {"url": f"data:{element.mime};base64,{b64}"}})

    stream_msg = cl.Message(content="Thinking...")
    await stream_msg.send()

    full_content = ""
    active_steps = {}
    tool_invocation_ids = {}   # run_id -> invocation_id
    tool_start_times = {}      # run_id -> start time (monotonic seconds)
    all_steps = []
    pending_edits = {}
    pending_commands = {}

    try:
        input_data = {"messages": [("user", content)]}
        config = {"recursion_limit": getattr(agent, '_iteration_limit', 200), "configurable": {"thread_id": thread_id}}

        while True:
            async for event in agent.astream_events(input_data, version="v2", config=config):
                kind = event["event"]
                run_id = event["run_id"]

                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"].content
                    if chunk:
                        if not full_content:
                            stream_msg.content = ""
                        full_content += chunk
                        await stream_msg.stream_token(chunk)

                elif kind == "on_tool_start":
                    tool_name = event["name"]
                    tool_input = event["data"].get("input")
                    display_map = {
                        "write_file": "Creating...", "read_file": "Analyzing...", "view_file": "Analyzing...",
                        "edit_file": "Editing...", "execute": "Executing...", "ls": "Listing...",
                        "grep_search": "Searching...", "write_todos": "Updating todos...", "think": "Thinking...",
                        "browser_screenshot": "📸 Screenshotting...", "browser_get_console_logs": "🖥️ Reading console...",
                        "browser_get_dom": "🔍 Reading DOM...", "browser_click_and_screenshot": "🖱️ Clicking...",
                        "browser_get_network_errors": "🌐 Checking network...",
                        "git_clone": "📥 Cloning repo...", "git_status": "🔍 Checking git status...",
                        "git_diff": "📄 Reading diff...", "git_log": "📜 Reading log...",
                        "git_blame": "🔎 Reading blame...", "git_commit": "💾 Committing...",
                        "git_create_branch": "🌿 Creating branch...", "git_checkout": "🔀 Checking out...",
                        "git_push": "🚀 Pushing...", "git_pull": "⬇️ Pulling...",
                        "git_stash": "📦 Stashing...", "git_generate_commit_message": "✍️ Generating commit message...",
                    }
                    display_name = f"{display_map.get(tool_name, f'Tool: {tool_name}')} {tool_input or ''}"
                    step = cl.Step(name=display_name, type="tool", parent_id=stream_msg.id)
                    step.input = str(tool_input) if tool_input else ""
                    await step.send()
                    active_steps[run_id] = step
                    all_steps.append(step)

                    try:
                        invocation_id = await record_tool_invocation_start(thread_id, tool_name)
                        tool_invocation_ids[run_id] = invocation_id
                        tool_start_times[run_id] = asyncio.get_event_loop().time()
                    except Exception as e:
                        logger.warning(f"record_tool_invocation_start failed: {e}")

                    if tool_name == "edit_file" and isinstance(tool_input, dict):
                        pending_edits[run_id] = {"type": "edit", "file_path": tool_input.get("file_path", ""),
                                                  "old_string": tool_input.get("old_string", ""), "new_string": tool_input.get("new_string", "")}
                    elif tool_name == "write_file" and isinstance(tool_input, dict):
                        pending_edits[run_id] = {"type": "write", "file_path": tool_input.get("file_path", ""),
                                                  "content": tool_input.get("content", "")}
                    elif tool_name == "execute" and isinstance(tool_input, dict):
                        pending_commands[run_id] = tool_input.get("command", "")

                elif kind == "on_tool_end":
                    step = active_steps.pop(run_id, None)
                    tool_output = event["data"].get("output")
                    tool_name = event["name"]
                    if step:
                        str_output = extract_tool_result(tool_output)
                        step.output = str_output[:500] + "..." if len(str_output) > 500 else str_output
                        await step.update()

                    try:
                        str_output_for_telemetry = extract_tool_result(tool_output)
                        invocation_id = tool_invocation_ids.pop(run_id, None)
                        start_time = tool_start_times.pop(run_id, None)
                        if invocation_id is not None:
                            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000 if start_time is not None else 0.0
                            status = "failure" if str_output_for_telemetry.startswith("Error") else "success"
                            await record_tool_invocation_end(invocation_id, duration_ms, status)
                    except Exception as e:
                        logger.warning(f"record_tool_invocation_end failed: {e}")

                    if tool_name in ("edit_file", "write_file") and run_id in pending_edits:
                        edit_info = pending_edits.pop(run_id)
                        result_msg = extract_tool_result(tool_output)
                        if not result_msg.startswith("Error"):
                            try:
                                diff_props = ({"filename": edit_info["file_path"], "old_str": "", "new_str": edit_info["content"],
                                               "result_msg": "✨ New file created", "is_new_file": True}
                                              if edit_info["type"] == "write" else
                                              {"filename": edit_info["file_path"], "old_str": edit_info["old_string"],
                                               "new_str": edit_info["new_string"], "result_msg": result_msg, "is_new_file": False})
                                await cl.CustomElement(name="DiffViewer", props=diff_props, display="inline").send(for_id=stream_msg.id)
                            except Exception as e:
                                logger.warning(f"DiffViewer render failed: {e}")

                            try:
                                if edit_info["type"] == "write":
                                    line_count = len(edit_info["content"].splitlines())
                                    await record_loc_event(thread_id, line_count)
                                elif edit_info["type"] == "edit":
                                    delta = len(edit_info["new_string"].splitlines()) - len(edit_info["old_string"].splitlines())
                                    if delta != 0:
                                        await record_loc_event(thread_id, delta)
                            except Exception as e:
                                logger.warning(f"record_loc_event failed: {e}")

                    if tool_name == "execute" and run_id in pending_commands:
                        cmd = pending_commands.pop(run_id)
                        output_str = extract_tool_result(tool_output)
                        if not output_str.startswith("Error: Execution not available"):
                            try:
                                await cl.CustomElement(name="TerminalOutput", props={"command": cmd, "output": output_str,
                                                        "exit_code": parse_exit_code(output_str)}, display="inline").send(for_id=stream_msg.id)
                            except Exception as e:
                                logger.warning(f"TerminalOutput render failed: {e}")

                    # Render git tool outputs inline
                    if tool_name == "git_diff":
                        result_str = extract_tool_result(tool_output)
                        if result_str and not result_str.startswith("Error"):
                            try:
                                await cl.CustomElement(
                                    name="DiffViewer",
                                    props={"filename": str(tool_input) if tool_input else "diff",
                                           "old_str": "", "new_str": result_str,
                                           "result_msg": "git diff", "is_new_file": False},
                                    display="inline",
                                ).send(for_id=stream_msg.id)
                            except Exception as e:
                                logger.warning(f"git_diff DiffViewer render failed: {e}")

                    elif tool_name in ("git_log", "git_status", "git_blame", "git_clone",
                                       "git_commit", "git_push", "git_pull",
                                       "git_create_branch", "git_checkout", "git_stash"):
                        result_str = extract_tool_result(tool_output)
                        if result_str and not result_str.startswith("Error"):
                            try:
                                await cl.CustomElement(
                                    name="TerminalOutput",
                                    props={"command": tool_name, "output": result_str, "exit_code": 0},
                                    display="inline",
                                ).send(for_id=stream_msg.id)
                            except Exception as e:
                                logger.warning(f"Git tool output render failed: {e}")

                    # Render browser tool outputs inline
                    if tool_name in ("browser_screenshot", "browser_click_and_screenshot"):
                        result_str = extract_tool_result(tool_output)
                        if result_str.startswith("data:image/png;base64,"):
                            try:
                                img_b64 = result_str.split(",", 1)[1]
                                img_bytes = base64.b64decode(img_b64)
                                await cl.Image(
                                    name=f"{tool_name}.png",
                                    content=img_bytes,
                                    mime="image/png",
                                    display="inline",
                                ).send(for_id=stream_msg.id)
                            except Exception as e:
                                logger.warning(f"Browser screenshot render failed: {e}")

                    elif tool_name in ("browser_get_console_logs", "browser_get_network_errors", "browser_get_dom"):
                        result_str = extract_tool_result(tool_output)
                        if result_str and not result_str.startswith("Error"):
                            try:
                                await cl.CustomElement(
                                    name="TerminalOutput",
                                    props={"command": tool_name, "output": result_str, "exit_code": 0},
                                    display="inline",
                                ).send(for_id=stream_msg.id)
                            except Exception as e:
                                logger.warning(f"Browser tool output render failed: {e}")

                    if tool_name == "write_todos" and tool_output:
                        try:
                            todos = None
                            if hasattr(tool_output, "update") and isinstance(tool_output.update, dict):
                                todos = tool_output.update.get("todos")
                            elif isinstance(tool_output, dict):
                                todos = tool_output.get("todos")
                            if todos:
                                await update_task_list(todos)
                        except Exception as e:
                            logger.warning(f"Todo update failed: {e}")

                elif kind == "on_tool_error":
                    step = active_steps.pop(run_id, None)
                    if step:
                        step.output = f"❌ Error: {event['data'].get('error', 'Unknown')}"
                        await step.update()

                elif kind == "on_chain_error":
                    logger.error(f"Chain Error: {event['data'].get('error')}")
                    await cl.Message(content=f"🚨 Backend Error: {event['data'].get('error')}").send()

                elif kind == "on_chat_model_end":
                    try:
                        output = event["data"].get("output")
                        usage = getattr(output, "usage_metadata", None) or getattr(output, "response_metadata", {}).get("token_usage", {})
                        if isinstance(usage, dict):
                            prompt_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
                            completion_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
                            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
                        else:
                            prompt_tokens = getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0)
                            completion_tokens = getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0)
                            total_tokens = getattr(usage, "total_tokens", prompt_tokens + completion_tokens)
                        model = getattr(output, "response_metadata", {}).get("model_name", "unknown") if output else "unknown"
                        await record_llm_call(thread_id, model, prompt_tokens, completion_tokens, total_tokens)
                    except Exception as e:
                        logger.warning(f"record_llm_call failed: {e}")

                elif kind == "on_chain_end":
                    try:
                        output = event["data"].get("output")
                        if output and isinstance(output, dict):
                            if "todos" in output:
                                await update_task_list(output["todos"])
                            if not full_content and "messages" in output:
                                messages = output["messages"]
                                if hasattr(messages, "value"): messages = messages.value
                                if isinstance(messages, list) and messages:
                                    last = messages[-1]
                                    is_ai = (hasattr(last, "type") and last.type == "ai") or \
                                            (isinstance(last, dict) and last.get("type") == "ai")
                                    if is_ai:
                                        full_content = getattr(last, "content", "") or last.get("content", "")
                    except Exception:
                        pass

            # Handle interrupts
            state = await agent.aget_state(config)
            if state and state.next:
                tasks = getattr(state, "tasks", [])
                if tasks and hasattr(tasks[0], "interrupts") and tasks[0].interrupts:
                    interrupt_info = tasks[0].interrupts[0].value
                    try:
                        if isinstance(interrupt_info, dict) and "action_requests" in interrupt_info:
                            reqs = interrupt_info["action_requests"]
                            cmd_str = "\n".join([f"{r.get('name')}: {r.get('args', {}).get('command', r.get('args'))}" for r in reqs])
                        else:
                            cmd_str = str(interrupt_info)
                    except Exception:
                        cmd_str = str(interrupt_info)

                    res = await cl.AskActionMessage(
                        content=f"⚠️ **Approval Required**\n```bash\n{cmd_str}\n```",
                        actions=[
                            cl.Action(name="approve", payload={"value": "approve"}, label="✅ Approve"),
                            cl.Action(name="reject", payload={"value": "reject"}, label="❌ Reject"),
                        ]
                    ).send()

                    user_response = (res.get("payload", {}).get("value") if res else "reject")
                    if user_response == "reject":
                        await cl.Message(content="🚫 Command execution rejected.").send()
                    input_data = Command(resume={"decisions": [{"type": user_response}]})
                    continue
            break

    except Exception as e:
        error_text = f"🚨 Error: {type(e).__name__}: {e}"
        logger.error(error_text, exc_info=True)
        stream_msg.content = error_text
        await stream_msg.update()
        return
    finally:
        if full_content:
            stream_msg.content = full_content
            await stream_msg.update()
        elif stream_msg.content == "Thinking...":
            stream_msg.content = "No text summary provided."
            await stream_msg.update()
        for step in all_steps:
            try:
                await step.remove()
            except Exception:
                pass


async def update_task_list(todos):
    task_list = cl.TaskList()
    for todo in todos:
        if not isinstance(todo, dict): continue
        title = todo.get("content", todo.get("title", "Untitled Task"))
        raw_status = todo.get("status", "pending")
        status = cl.TaskStatus.DONE if raw_status == "done" else (cl.TaskStatus.RUNNING if raw_status == "in_progress" else cl.TaskStatus.READY)
        await task_list.add_task(cl.Task(title=str(title), status=status))
    try:
        await task_list.send()
    except Exception:
        pass


def parse_exit_code(output_str):
    import re
    if not output_str:
        return None
    match = re.search(r"exit code (\d+)", output_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0 if "Command succeeded" in output_str or "Successfully" in output_str else None


def extract_tool_result(tool_output):
    if tool_output is None: return ""
    if isinstance(tool_output, str): return tool_output
    if hasattr(tool_output, "content"): return str(tool_output.content)
    if isinstance(tool_output, dict): return tool_output.get("content", str(tool_output))
    return str(tool_output)
