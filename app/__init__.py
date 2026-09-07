"""
Loads .env into the process environment before any submodule of this
package runs its own top-level code.

This has to live here, not in app/main.py, because Python guarantees a
parent package's __init__.py executes before any of its submodules --
`from app.core.llm.router import active_provider`, `from app.db.session
import DATABASE_URL`, and `from app.main import app` all trigger this
file first, regardless of which one is imported first. Putting the call
in main.py instead would only cover the actual running API server (the
uvicorn entrypoint) and silently miss .env for anything else that
imports a submodule directly -- a one-off script, a REPL session, or a
test file that doesn't happen to import app.main. This way there's
exactly one place .env loading can be missed: never.

Safe to import app.* multiple times or from multiple entrypoints --
load_dotenv() is idempotent, and Python only runs this file once per
process regardless of how many times "app" is imported.
"""
from dotenv import load_dotenv

load_dotenv()
