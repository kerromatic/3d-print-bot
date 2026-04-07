#!/usr/bin/env python3
"""
Run the Telegram bot, dashboard API, and camera server.
Usage:
    python run.py           # Runs all services
    python run.py --bot     # Bot only
    python run.py --api     # API/dashboard only
    python run.py --cam     # Camera server only
"""

import os
import sys
import argparse
import threading
import subprocess


def run_bot():
    """Start the Telegram bot."""
    subprocess.run(
        [sys.executable, "main.py"],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )


def run_api():
    """Start the FastAPI dashboard server."""
    port = os.getenv("API_PORT", "8000")
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "api.server:app",
         "--host", "0.0.0.0", "--port", port],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )


def run_cam():
    """Start the camera server."""
    port = os.getenv("CAM_SERVER_PORT", "8001")
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "cam_server:app",
         "--host", "0.0.0.0", "--port", port],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )


def run_all():
    """Run all services concurrently."""
    api_thread = threading.Thread(target=run_api, daemon=True)
    cam_thread = threading.Thread(target=run_cam, daemon=True)

    api_thread.start()
    cam_thread.start()

    # Bot runs in main thread
    run_bot()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run 3D Print Hub services")
    parser.add_argument("--bot", action="store_true", help="Bot only")
    parser.add_argument("--api", action="store_true", help="API/dashboard only")
    parser.add_argument("--cam", action="store_true", help="Camera server only")
    args = parser.parse_args()

    if args.bot:
        run_bot()
    elif args.api:
        run_api()
    elif args.cam:
        run_cam()
    else:
        run_all()
