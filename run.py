#!/usr/bin/env python3
"""
Run both the Telegram bot and the dashboard API server.
Usage:
    python run.py           # Runs both bot + API
    python run.py --bot     # Bot only
    python run.py --api     # API/dashboard only
"""

import argparse
import asyncio
import subprocess
import sys
import os


def run_bot():
    """Start the Telegram bot."""
    print("ÃÂ°ÃÂÃÂ¤ÃÂ Starting Telegram bot...")
    subprocess.run([sys.executable, "main.py"], cwd=os.path.dirname(__file__))


def run_api():
    """Start the FastAPI dashboard server."""
    port = os.getenv("API_PORT", "8000")
    print(f"ÃÂ°ÃÂÃÂÃÂ Starting dashboard API on http://localhost:{port}")
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "api.server:app",
        "--host", "0.0.0.0",
        "--port", port,
        "--reload",
    ], cwd=os.path.dirname(__file__))


def run_cam():
    """Start the standalone camera server."""
    from config.settings import settings
    if not settings.PRINTER_IP:
        print("Camera not configured (PRINTER_IP missing), skipping cam server")
        return
    port = settings.CAM_SERVER_PORT
    print(f"\ud83d\udcf7 Starting live camera on http://localhost:{port}")
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "cam_server:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--log-level", "warning",
    ], cwd=os.path.dirname(__file__))


def run_both():
    """Start both bot and API in parallel."""
    from concurrent.futures import ProcessPoolExecutor
    print("ÃÂ°ÃÂÃÂÃÂ Starting 3D Print Hub (Bot + Dashboard)...\n")
    with ProcessPoolExecutor(max_workers=3) as executor:
        executor.submit(run_bot)
        executor.submit(run_api)
        executor.submit(run_cam)


def main():
    parser = argparse.ArgumentParser(description="3D Print Hub Runner")
    parser.add_argument("--bot", action="store_true", help="Run bot only")
    parser.add_argument("--cam", action="store_true", help="Camera server only")
    parser.add_argument("--api", action="store_true", help="Run API/dashboard only")
    args = parser.parse_args()

    if args.bot:
        run_bot()
    elif args.cam:
        run_cam()
    elif args.api:
        run_api()
    else:
        run_both()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Run both the Telegram bot and the dashboard API server.
Usage:
    python run.py           # Runs both bot + API
    python run.py --bot     # Bot only
    python run.py --api     # API/dashboard only
"""

import argparse
import asyncio
import subprocess
import sys
import os


def run_bot():
    """Start the Telegram bot."""
    print("Ã°ÂÂ¤Â Starting Telegram bot...")
    subprocess.run([sys.executable, "main.py"], cwd=os.path.dirname(__file__))


def run_api():
    """Start the FastAPI dashboard server."""
    port = os.getenv("API_PORT", "8000")
    print(f"Ã°ÂÂÂ Starting dashboard API on http://localhost:{port}")
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "api.server:app",
        "--host", "0.0.0.0",
        "--port", port,
        "--reload",
    ], cwd=os.path.dirname(__file__))


def run_both():
    """Start both bot and API in parallel."""
    from concurrent.futures import ProcessPoolExecutor
    print("Ã°ÂÂÂ Starting 3D Print Hub (Bot + Dashboard)...\n")
    with ProcessPoolExecutor(max_workers=2) as executor:
        executor.submit(run_bot)
        executor.submit(run_api)


def main():
    parser = argparse.ArgumentParser(description="3D Print Hub Runner")
    parser.add_argument("--bot", action="store_true", help="Run bot only")
    parser.add_argument("--api", action="store_true", help="Run API/dashboard only")
    args = parser.parse_args()

    if args.bot:
        run_bot()
    elif args.api:
        run_api()
    else:
        run_both()


if __name__ == "__main__":
    main()
