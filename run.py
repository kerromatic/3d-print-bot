#!/usr/bin/env python3
"""
Run the Telegram bot, dashboard API, and camera server.
Usage:
    python run.py           # Runs all services
    python run.py --bot     # Bot only
    python run.py --api     # API/dashboard only
    python run.py --cam     # Camera server only
"""

import argparse
import subprocess
import sys
import os
import threading
import time


def run_bot():
    """Start the Telegram bot."""
    subprocess.run(
        [sys.executable, "main.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
    )


def run_api():
    """Start the FastAPI dashboard server."""
    port = os.getenv("API_PORT", "8000")
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "api.server:app",
         "--host", "0.0.0.0", "--port", port, "--reload"],
        cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
    )


def run_cam():
    """Start the standalone camera server."""
    # Load settings to check if camera is configured
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config.settings import settings
    if not settings.PRINTER_IP:
        print("Camera not configured (PRINTER_IP missing), skipping cam server")
        return
    port = str(settings.CAM_SERVER_PORT)
    print(f"Starting live camera on http://localhost:{port}")
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "cam_server:app",
         "--host", "0.0.0.0", "--port", port, "--log-level", "warning"],
        cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
    )


def run_all():
    """Start all services using threads."""
    print("Starting 3D Print Hub (Bot + Dashboard + Camera)...\n")

    # Start API in a thread
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    print("Started dashboard API on http://localhost:8000")

    # Start camera server in a thread
    cam_thread = threading.Thread(target=run_cam, daemon=True)
    cam_thread.start()

    # Small delay to let the other services start
    time.sleep(2)

    print("Starting Telegram bot...")
    # Run bot in the main thread (it handles signals properly)
    run_bot()


def main():
    parser = argparse.ArgumentParser(description="3D Print Hub Runner")
    parser.add_argument("--bot", action="store_true", help="Run bot only")
    parser.add_argument("--cam", action="store_true", help="Camera server only")
    parser.add_argument("--api", action="store_true", help="API/dashboard only")
    args = parser.parse_args()

    if args.bot:
        run_bot()
    elif args.cam:
        run_cam()
    elif args.api:
        run_api()
    else:
        run_all()


if __name__ == "__main__":
    main()
