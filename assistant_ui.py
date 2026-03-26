import chainlit as cl
import os
import asyncio
import logging
import uuid
import base64
from coding_assistant import create_coding_assistant

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AssistantUI")

@cl.on_chat_start
async def start():
    # 1. Ask for workspace folder name to construct the path
    res = await cl.AskUserMessage(content="Enter the project folder name (sibling to ai-intern):").send()
    if res:
        project_folder = res['output'].strip()
        
        # Calculate full path relative to parent directory
        # D:\...\ALLPROJECTS\ai-intern -> D:\...\ALLPROJECTS\
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        workspace = os.path.join(parent_dir, project_folder)
        workspace = os.path.abspath(workspace)

        cl.user_session.set("workspace", workspace)
        
        try:
            # Show status messages to keep user engaged
            msg = cl.Message(content="🏗️ Creating agents...")
            await msg.send()
            
            await asyncio.sleep(0.8)
            msg.content = "🔧 Loading tools into agent..."
            await msg.update()

            # Create the agent using our helper (now async to load MCP tools)
            agent = await create_coding_assistant(workspace)
            cl.user_session.set("agent", agent)

            # Generate a unique thread_id for this session's memory
            thread_id = str(uuid.uuid4())
            cl.user_session.set("thread_id", thread_id)
            logger.info(f"Session started with thread_id: {thread_id}")
            
            # Persistent TaskList for the sidebar
            task_list = cl.TaskList()
            await task_list.send()
            cl.user_session.set("task_list", task_list)
            
            # Final ready message
            msg.content = f"🚀 AI Coding Assistant ready for: **{workspace}**"
            await msg.update()
        except Exception as e:
            await cl.Message(content=f"❌ Error initializing agent: {e}").send()

@cl.on_message
async def main(message: cl.Message):
    agent = cl.user_session.get("agent")
    task_list = cl.user_session.get("task_list")
    thread_id = cl.user_session.get("thread_id")
    
    if not agent:
        await cl.Message(content="Session expired or agent not ready. Please refresh.").send()
        return

    # 1. Prepare message content (multi-modal support for images)
    content = [{"type": "text", "text": message.content or ""}]
    
    for element in message.elements:
        if "image" in element.mime:
            image_data = None
            if element.content:
                image_data = element.content
            elif element.path and os.path.exists(element.path):
                with open(element.path, "rb") as f:
                    image_data = f.read()
            
            if image_data:
                base64_image = base64.b64encode(image_data).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{element.mime};base64,{base64_image}"
                    }
                })

    # 2. Initialize Thinking Placeholder
    stream_msg = cl.Message(content="Thinking...")
    await stream_msg.send()
    
    full_content = ""
    active_steps = {}
    all_steps = []
    pending_edits = {}  # Capture edit_file inputs for diff rendering
    pending_commands = {}  # Capture execute tool commands for terminal rendering

    try:
        # 3. Run the agent with astream_events
        input_data = {"messages": [("user", content)]}
        logger.info(f"Starting agent with input: {message.content} (plus {len(content)-1} images)")
        config = {"recursion_limit": 200, "configurable": {"thread_id": thread_id}}
        async for event in agent.astream_events(input_data, version="v2", config=config):
            kind = event["event"]
            run_id = event["run_id"]
            logger.info(f"Event: {kind} | name={event.get('name', '?')}")

            # Stream tokens
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    if not full_content:
                        stream_msg.content = ""
                    full_content += content
                    await stream_msg.stream_token(content)

            # Tool steps
            elif kind == "on_tool_start":
                # Custom display names for tools
                tool_name = event["name"]
                tool_input = event["data"].get("input")
                display_map = {
                    "write_file": "Creating...",
                    "read_file": "Analyzing...",
                    "view_file": "Analyzing...",
                    "edit_file": "Editing...",
                    "execute": "Executing...",
                    "ls": "Listing...",
                    "grep_search": "Searching...",
                    # "find_by_name": "Searching...",
                    "write_todos": "Updating todos...",
                    "think": "Thinking...",
                }
                display_name = f"{display_map.get(tool_name, f'Tool: {tool_name}')} {tool_input or ''}"
                
                step = cl.Step(name=display_name, type="tool", parent_id=stream_msg.id)
                step.input = str(tool_input) if tool_input else ""
                await step.send()
                active_steps[run_id] = step
                all_steps.append(step)
                
                # Capture edit_file inputs for diff rendering
                if event["name"] == "edit_file" and isinstance(tool_input, dict):
                    pending_edits[run_id] = {
                        "type": "edit",
                        "file_path": tool_input.get("file_path", ""),
                        "old_string": tool_input.get("old_string", ""),
                        "new_string": tool_input.get("new_string", ""),
                    }
                # Capture write_file inputs for new-file rendering
                elif event["name"] == "write_file" and isinstance(tool_input, dict):
                    pending_edits[run_id] = {
                        "type": "write",
                        "file_path": tool_input.get("file_path", ""),
                        "content": tool_input.get("content", ""),
                    }
                # Capture execute command for terminal rendering
                elif event["name"] == "execute" and isinstance(tool_input, dict):
                    pending_commands[run_id] = tool_input.get("command", "")

            elif kind == "on_tool_end":
                step = active_steps.get(run_id)
                tool_output = event["data"].get("output")
                tool_name = event["name"]
                
                if step:
                    str_output = extract_tool_result(tool_output)
                    if len(str_output) > 500:
                        str_output = str_output[:500] + "..."
                    step.output = str_output
                    await step.update()
                    del active_steps[run_id]

                # Render diffs for edit_file / write_file using captured input
                if tool_name in ("edit_file", "write_file") and run_id in pending_edits:
                    edit_info = pending_edits.pop(run_id)
                    result_msg = extract_tool_result(tool_output)
                    
                    # If the tool returned an error, don't show the diff viewer
                    if result_msg.startswith("Error"):
                        logger.warning(f"{tool_name} error: {result_msg}")
                    else:
                        try:
                            if edit_info["type"] == "write":
                                # New file: empty old_str, full content as new_str (all green)
                                diff_props = {
                                    "filename": edit_info["file_path"],
                                    "old_str": "",
                                    "new_str": edit_info["content"],
                                    "result_msg": f"✨ New file created",
                                    "is_new_file": True,
                                }
                            else:
                                # Edit: show old_str → new_str diff
                                diff_props = {
                                    "filename": edit_info["file_path"],
                                    "old_str": edit_info["old_string"],
                                    "new_str": edit_info["new_string"],
                                    "result_msg": result_msg,
                                    "is_new_file": False,
                                }
                            diff_el = cl.CustomElement(
                                name="DiffViewer",
                                props=diff_props,
                                display="inline",
                            )
                            await diff_el.send(for_id=stream_msg.id)
                        except Exception as e:
                            logger.warning(f"DiffViewer render failed: {e}")

                # Render terminal output for execute tool
                if tool_name == "execute" and run_id in pending_commands:
                    cmd = pending_commands.pop(run_id)
                    output_str = extract_tool_result(tool_output)
                    if not output_str.startswith("Error: Execution not available"):
                        try:
                            exit_code = parse_exit_code(output_str)
                            term_el = cl.CustomElement(
                                name="TerminalOutput",
                                props={
                                    "command": cmd,
                                    "output": output_str,
                                    "exit_code": exit_code,
                                },
                                display="inline",
                            )
                            await term_el.send(for_id=stream_msg.id)
                        except Exception as e:
                            logger.warning(f"TerminalOutput render failed: {e}")

                # Real-time todos
                if tool_name == "write_todos" and tool_output:
                    try:
                        todos = None
                        if hasattr(tool_output, "update") and isinstance(tool_output.update, dict) and "todos" in tool_output.update:
                            todos = tool_output.update["todos"]
                        elif isinstance(tool_output, dict) and "todos" in tool_output:
                            todos = tool_output["todos"]
                        if todos:
                            await update_task_list(todos)
                    except Exception as e:
                        logger.warning(f"Todo update failed: {e}")

            elif kind == "on_tool_error":
                error_msg = str(event["data"].get("error", "Unknown tool error"))
                logger.error(f"Tool Error ({event.get('name')}): {error_msg}")
                step = active_steps.get(run_id)
                if step:
                    step.output = f"❌ Error: {error_msg}"
                    await step.update()

            elif kind == "on_chain_error":
                error_msg = str(event["data"].get("error", "Unknown chain error"))
                logger.error(f"Chain Error: {error_msg}")
                await cl.Message(content=f"🚨 Backend Error: {error_msg}").send()

            # Final response fallback
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
                                last_msg = messages[-1]
                                is_ai = (hasattr(last_msg, "type") and last_msg.type == "ai") or \
                                         (isinstance(last_msg, dict) and (last_msg.get("type") == "ai" or last_msg.get("role") == "assistant"))
                                if is_ai:
                                    final_text = getattr(last_msg, "content", "") if not isinstance(last_msg, dict) else last_msg.get("content", "")
                                    if final_text:
                                        full_content = final_text
                except Exception:
                    pass

    except Exception as e:
        # Catch-all: show the error in UI so user sees it
        error_text = f"🚨 Error: {type(e).__name__}: {e}"
        logger.error(error_text, exc_info=True)
        stream_msg.content = error_text
        await stream_msg.update()
        return

    finally:
        # Final UI cleanup
        if full_content:
            stream_msg.content = full_content
            await stream_msg.update()
        elif stream_msg.content == "Thinking...":
            stream_msg.content = "No text summary provided."
            await stream_msg.update()
            
        # Remove tool steps from the UI
        for step in all_steps:
            try:
                await step.remove()
            except Exception:
                pass

async def update_task_list(todos):
    """Helper to refresh the sidebar TaskList"""
    task_list = cl.TaskList()
    for todo in todos:
        if not isinstance(todo, dict): continue
        title = todo.get("content", todo.get("title", "Untitled Task"))
        raw_status = todo.get("status", "pending")
        if raw_status == "done": status = cl.TaskStatus.DONE
        elif raw_status == "in_progress": status = cl.TaskStatus.RUNNING
        else: status = cl.TaskStatus.READY
        task = cl.Task(title=str(title), status=status)
        await task_list.add_task(task)
    try:
        await task_list.send()
    except Exception:
        pass

def parse_exit_code(output_str):
    """
    Extracts the exit code from the tool output string.
    The deepagents LocalShellBackend appends 'Exit code: N' at the end.
    """
    import re
    if not output_str:
        return None
        
    # Look for 'Exit code: N' or '[Command ... with exit code N]'
    match = re.search(r"exit code (\d+)", output_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
        
    # If output contains succeeded but no code, assume 0
    if "Command succeeded" in output_str:
        return 0
        
    return 0 if "Successfully" in output_str else None

def extract_tool_result(tool_output):
    """Extract string content from various tool output types."""
    if tool_output is None:
        return ""
    if isinstance(tool_output, str):
        return tool_output
    # Handle ToolMessage from deepagents
    if hasattr(tool_output, "content"):
        return str(tool_output.content)
    # Handle dictionary representation
    if isinstance(tool_output, dict):
        return tool_output.get("content", str(tool_output))
    return str(tool_output)

# To run: chainlit run assistant_ui.py
