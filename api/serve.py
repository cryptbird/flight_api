"""
Vercel serverless entry: expose the ASGI application as ``app``.

Route: ``/api/serve`` — ``vercel.json`` rewrites all paths here.

Set Vercel **Root Directory** to this repo folder (the one containing ``api/``, ``app/``,
``requirements.txt``), not the parent monorepo root, or this file will not deploy.
"""

from app.main import app

__all__ = ["app"]
