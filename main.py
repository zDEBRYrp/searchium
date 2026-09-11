"""
Searchium - Advanced file search engine powered by AI

Main application entry point. Initialization logic extracted to core/initialization.py
and frontend routing to core/frontend.py.
"""

import os
import socket
import subprocess
import sys
import threading

# Prevent python from crashing on macOS when calling fork() in multithreaded apps.
# e.g. during subprocess.run inside a uvicorn/fastapi worker thread.
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

from searchium.api.v1.router import api_router
from searchium.core.config import settings
from searchium.core.factory import create_app
from searchium.core.frontend import setup_frontend_routes
from searchium.core.initialization import (
    critical_init,
    health_monitoring_loop,
)
from searchium.core.logging import logger
from searchium.core.telemetry import telemetry
from searchium.services.crawler.manager import get_crawl_job_manager

# Global variable to track Vite process
_vite_process = None


def startup_handler():
    """Application startup handler."""
    global _vite_process

    logger.info("=" * 50)
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info("=" * 50)

    telemetry.capture_event("application_start")

    try:
        # Start Typesense
        from searchium.services.typesense_manager import get_typesense_manager
        ts = get_typesense_manager()
        if not ts.is_running():
            if not ts.is_installed():
                logger.info("Typesense not found, downloading...")
            if ts.start():
                if ts.wait_until_ready(timeout=30):
                    logger.info("Typesense ready")
                else:
                    logger.warning("Typesense started but not responding yet")
            else:
                logger.error("Failed to start Typesense - search will be unavailable")

        critical_init()

        # Initialize all services so initialization stream reaches 100%
        from searchium.core.initialization import (
            init_typesense_for_wizard,
            init_tika_for_wizard,
            init_crawl_manager_for_wizard,
        )
        init_typesense_for_wizard()
        init_tika_for_wizard()
        init_crawl_manager_for_wizard()

        logger.info("All services initialized")

        if settings.debug:
            logger.info("Debug mode enabled: Starting Vite dev server...")
            frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
            _vite_process = subprocess.Popen(
                ["npm", "run", "dev", "--", "--port", str(settings.frontend_dev_port), "--strictPort"],
                cwd=frontend_dir,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            logger.info(f"Vite dev server started (PID: {_vite_process.pid})")

        monitor_thread = threading.Thread(target=health_monitoring_loop, daemon=True, name="health_monitor")
        monitor_thread.start()
    except Exception as e:
        logger.error(f"Critical initialization failed: {e}")
        telemetry.capture_exception(e)
        raise


def shutdown_handler():
    """Application shutdown handler."""
    global _vite_process
    perform_shutdown(_vite_process)


def perform_shutdown(vite_process=None):
    """Perform application shutdown tasks."""
    try:
        # Trigger Typesense snapshot before shutdown
        try:
            from searchium.services.typesense_client import get_typesense_client

            logger.info("рџ“ё Creating Typesense snapshot before shutdown...")
            typesense = get_typesense_client()
            if typesense.collection_ready:
                # Trigger snapshot via API (uses Typesense default behavior)
                typesense.client.operations.perform("snapshot", {})
                logger.info("вњ… Snapshot created successfully")
            else:
                logger.debug("в„№пёЏ  Skipping snapshot: Collection not ready (first run or not completed)")
        except Exception as e:
            logger.warning(f"вљ пёЏ Failed to create snapshot on shutdown: {e}")
            telemetry.capture_exception(e)

        # Stop Typesense
        try:
            from searchium.services.typesense_manager import get_typesense_manager
            get_typesense_manager().stop()
        except Exception:
            pass

        if vite_process:
            logger.info("рџ›‘ Stopping Vite dev server...")
            vite_process.terminate()
            try:
                vite_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vite_process.kill()
            logger.info("вњ… Vite dev server stopped")

        crawl_manager = get_crawl_job_manager()
        if crawl_manager.is_running():
            crawl_manager.stop_crawl()
            logger.info("вњ… Crawl manager stopped")

        # Shutdown telemetry (flushes batched events and captures shutdown event)
        logger.debug("рџ“Љ Shutting down telemetry...")
        telemetry.shutdown()
        logger.debug("вњ… Telemetry shutdown complete")

    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        telemetry.capture_exception(e)
    logger.info("рџ‘‹ Application shutdown complete")


def on_shutdown_sync():
    """Sync wrapper for FlaskWebGUI's on_shutdown callback."""
    logger.info("Browser closed, initiating shutdown...")
    perform_shutdown()
    import sys
    os._exit(0)


# Create FastAPI application
app = create_app()

# Register startup and shutdown event handlers
app.add_event_handler("startup", startup_handler)
app.add_event_handler("shutdown", shutdown_handler)

# Include API v1 router
app.include_router(api_router)

# Setup frontend routes
# Determine frontend dist path
source_frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
frontend_dist_path = None

# 1. Try source (dev mode)
if os.path.exists(source_frontend_path):
    frontend_dist_path = source_frontend_path
    logger.debug(f"Using frontend from source: {frontend_dist_path}")

# 2. Try installed package (production mode)
if not frontend_dist_path:
    try:
        from importlib.resources import files

        # Check resources in the 'searchium.frontend' subpackage
        frontend_pkg_path = files("searchium.frontend") / "dist"
        if frontend_pkg_path.is_dir():
            frontend_dist_path = str(frontend_pkg_path)
            logger.debug(f"Using frontend from installed package: {frontend_dist_path}")
    except Exception as e:
        logger.debug(f"Could not locate frontend via importlib.resources: {e}")

# 3. Fallback
if not frontend_dist_path:
    logger.warning("Frontend dist directory not found in source or package")
    frontend_dist_path = source_frontend_path

setup_frontend_routes(app, frontend_dist_path)


@app.get("/health")
def health_check():
    """Combined health and info endpoint."""
    from searchium.services.service_manager import get_service_manager

    service_manager = get_service_manager()
    health_status = service_manager.check_all_services_health()

    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "api_version": "v1",
        "services": health_status,
    }


def get_available_port(start_port: int, max_attempts: int = 100) -> int:
    """Finds an available port starting from start_port."""
    port = start_port
    while port < start_port + max_attempts:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((settings.host, port))
                return port
            except OSError:
                port += 1
    return start_port


def build_desktop_server_command(port: int) -> list[str]:
    """Build the uvicorn command used for desktop production launches."""
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "searchium.main:app",
        "--host",
        settings.host,
        "--port",
        str(port),
        "--log-level",
        "info",
    ]


def _run_macos_desktop_app(port: int) -> None:
    """Launch the desktop app on macOS without forking the backend process."""
    from searchium.lib.flaskwebgui import FlaskUI, close_application

    server_env = os.environ.copy()
    server_env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    server_process = subprocess.Popen(
        build_desktop_server_command(port),
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=server_env,
    )

    ui = FlaskUI(
        app=app,
        server="fastapi",
        port=port,
        width=1200,
        height=800,
        on_shutdown=None,
    )
    browser_thread = threading.Thread(target=ui.start_browser, args=(server_process,), name="desktop_browser")

    try:
        browser_thread.start()
        server_process.wait()
    except KeyboardInterrupt:
        logger.info("рџ›‘ Desktop app interrupted, shutting down...")
    finally:
        if server_process.poll() is None:
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=5)

        if browser_thread.is_alive():
            close_application()

        browser_thread.join()


def run_production_desktop_app(port: int) -> None:
    """Run the production desktop UI with a platform-appropriate backend launcher."""
    if sys.platform == "darwin":
        _run_macos_desktop_app(port)
        return

    from searchium.lib.flaskwebgui import FlaskUI

    FlaskUI(
        app=app,
        server="fastapi",
        port=port,
        width=1200,
        height=800,
        on_shutdown=on_shutdown_sync,
    ).run()


def cli_main():
    """Entry point for packaged distribution (production mode only)."""
    # Set DEBUG=false to ensure FlaskWebGUI suppresses third-party debug logs
    # This must be set BEFORE importing FlaskWebGUI
    os.environ["DEBUG"] = "false"

    # Handle Ctrl+C properly - close browser and exit
    import signal

    def signal_handler(sig, frame):
        logger.info("Interrupt received, shutting down...")
        try:
            from searchium.lib.flaskwebgui import FLASKWEBGUI_BROWSER_PROCESS
            if FLASKWEBGUI_BROWSER_PROCESS and FLASKWEBGUI_BROWSER_PROCESS.poll() is None:
                FLASKWEBGUI_BROWSER_PROCESS.terminate()
                try:
                    FLASKWEBGUI_BROWSER_PROCESS.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    FLASKWEBGUI_BROWSER_PROCESS.kill()
        except Exception:
            pass
        perform_shutdown()
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    port = get_available_port(settings.port)
    logger.info(f"Starting {settings.app_name} on http://localhost:{port}")
    logger.info("рџЏ­ Running in PRODUCTION mode")

    run_production_desktop_app(port)


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run Searchium application")
    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        default=None,
        help="Force run mode (dev/prod). If not set, uses DEBUG env var.",
    )
    args = parser.parse_args()

    # Mode override from CLI
    if args.mode == "dev":
        settings.debug = True
        os.environ["DEBUG"] = "true"
        logger.info("рџ”§ Mode forced to DEVELOPMENT via CLI")
    elif args.mode == "prod":
        settings.debug = False
        os.environ["DEBUG"] = "false"
        logger.info("рџЏ­ Mode forced to PRODUCTION via CLI")
    else:
        mode_str = "DEVELOPMENT" if settings.debug else "PRODUCTION"
        logger.info(f"в„№пёЏ  Running in {mode_str} mode (from environment)")

    port = get_available_port(settings.port)
    logger.info(f"Starting {settings.app_name} on http://localhost:{port}")

    if settings.debug:
        uvicorn.run("searchium.main:app", host=settings.host, port=port, reload=True, log_level="info")
    else:
        run_production_desktop_app(port)
