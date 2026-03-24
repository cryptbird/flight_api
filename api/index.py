"""
Vercel serverless entry: ASGI app must be exposed as ``app`` in this module.

Set the Vercel project **Root Directory** to the folder that contains ``api/``, ``app/``,
and ``requirements.txt`` (typically ``flight_api``).
"""

from app.main import app

__all__ = ["app"]
