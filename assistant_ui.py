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
from coding_assistant import create_coding_assistant
from langgraph.types import Command

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AssistantUI")

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
_store = InMemoryStore()

async def get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        import aiosqlite
        conn = await aiosqlite.connect("agent_data/checkpoints_lg.db")
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()
    return _checkpointer


@cl.on_chat_start
async def start():
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
        agent = await create_coding_assistant(workspace, checkpointer, _store, user_id=user_id)
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
        agent = await create_coding_assistant(workspace, checkpointer, _store, user_id=user_id)

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
    all_steps = []
    pending_edits = {}
    pending_commands = {}

    try:
        input_data = {"messages": [("user", content)]}
        config = {"recursion_limit": 200, "configurable": {"thread_id": thread_id}}

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
                    }
                    display_name = f"{display_map.get(tool_name, f'Tool: {tool_name}')} {tool_input or ''}"
                    step = cl.Step(name=display_name, type="tool", parent_id=stream_msg.id)
                    step.input = str(tool_input) if tool_input else ""
                    await step.send()
                    active_steps[run_id] = step
                    all_steps.append(step)

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

                    if tool_name == "execute" and run_id in pending_commands:
                        cmd = pending_commands.pop(run_id)
                        output_str = extract_tool_result(tool_output)
                        if not output_str.startswith("Error: Execution not available"):
                            try:
                                await cl.CustomElement(name="TerminalOutput", props={"command": cmd, "output": output_str,
                                                        "exit_code": parse_exit_code(output_str)}, display="inline").send(for_id=stream_msg.id)
                            except Exception as e:
                                logger.warning(f"TerminalOutput render failed: {e}")

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
