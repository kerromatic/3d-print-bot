"""
Simple authentication middleware for the dashboard.
Adds HTTP Basic Auth to protect the dashboard when accessed remotely.
"""

import os
import secrets
from fastapi import Request, Response
from fastapi.responses import HTMLResponse
import base64


def check_auth(request: Request) -> bool:
    """Check if the request has valid authentication.
    Returns True if auth is valid or not required (no password set).
    """
    password = os.getenv("DASH_PASSWORD", "")
    if not password:
        return True  # No password set, allow access
    
    username = os.getenv("DASH_USERNAME", "admin")
    
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False
    
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        req_user, req_pass = decoded.split(":", 1)
        return secrets.compare_digest(req_user, username) and secrets.compare_digest(req_pass, password)
    except Exception:
        return False


def auth_response() -> Response:
    """Return a 401 response requesting authentication."""
    return Response(
        content="Authentication required",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="3D Print Hub Dashboard"'},
    )
