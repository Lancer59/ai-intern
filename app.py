"""
Production entry point for the AI Coding Assistant.

Combines the Chainlit UI and the dashboard FastAPI backend into a single ASGI app.

Run with:
    uvicorn app:app --host 127.0.0.1 --port 8000

For development (Chainlit only, with hot-reload):
    chainlit run assistant_ui.py
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from chainlit.utils import mount_chainlit
from dashboard.api import dashboard_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Close the persistent aiosqlite connection
    try:
        import assistant_ui
        if assistant_ui._checkpointer_conn is not None:
            await assistant_ui._checkpointer_conn.close()
    except Exception:
        pass
    # Force-exit to kill any lingering background threads (socketio, aiosqlite, etc.)
    import os
    os._exit(0)


# Main ASGI app
app = FastAPI(title="AI Coding Assistant", lifespan=lifespan)

# Include all dashboard routes directly into the main app.
# dashboard_app routes already carry the /dashboard prefix, so appending them
# to the main app's route list makes them available at the top level without
# an extra path prefix.
for route in dashboard_app.routes:
    app.routes.append(route)

# Mount Chainlit at the root path.
# mount_chainlit registers the Chainlit ASGI sub-application and its
# socket.io/websocket handlers onto `app` at the given path.
mount_chainlit(app=app, target="assistant_ui.py", path="/")
