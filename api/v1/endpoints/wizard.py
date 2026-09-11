"""
Wizard API Endpoints - Handles initialization wizard steps
"""

import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from searchium.api.v1.sse import sse_response
from searchium.core.logging import logger
from searchium.database.models import db_session
from searchium.database.repositories.wizard_state_repository import WizardStateRepository
from searchium.services.docker_manager import get_docker_manager
from searchium.services.startup_checker import CheckDetail, get_startup_checker
from searchium.services.typesense_client import get_typesense_client

router = APIRouter(prefix="/wizard", tags=["wizard"])


class WizardStatusResponse(BaseModel):
    """Response model for wizard status"""

    wizard_completed: bool
    docker_check_passed: bool
    docker_services_started: bool
    collection_created: bool
    last_step_completed: int
    current_step: int


class DockerCheckResponse(BaseModel):
    """Response model for docker check"""

    available: bool
    command: Optional[str] = None
    version: Optional[str] = None
    has_gpu_hardware: bool = False
    has_nvidia_runtime: bool = False
    gpu_mode_enabled: bool = False
    error: Optional[str] = None


class DockerStartResponse(BaseModel):
    """Response model for docker start"""

    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


class DockerStatusResponse(BaseModel):
    """Response model for docker status"""

    success: bool
    running: bool
    healthy: bool
    services: list
    error: Optional[str] = None


class CollectionCreateResponse(BaseModel):
    """Response model for collection creation"""

    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


class CollectionStatusResponse(BaseModel):
    """Response model for collection status"""

    exists: bool
    ready: bool
    document_count: Optional[int] = None
    error: Optional[str] = None


class CheckDetailResponse(BaseModel):
    """Response model for individual check detail"""

    passed: bool
    message: str


class StartupCheckResponse(BaseModel):
    """Response model for comprehensive startup checks"""

    all_checks_passed: bool
    needs_wizard: bool
    is_first_run: bool  # True if wizard was never completed
    start_step: Optional[int] = None
    is_upgrade: bool
    checks: dict  # Maps check name to CheckDetailResponse


class DatabaseUpgradeResponse(BaseModel):
    """Response model for database upgrade"""

    success: bool
    message: str
    logs: list[str]


@router.get("/status", response_model=WizardStatusResponse)
def get_wizard_status():
    """Get current wizard completion status"""
    try:
        with db_session() as db:
            repo = WizardStateRepository(db)
            state = repo.get_or_create()

            docker_check = True
            docker_started = True

            if state.wizard_completed:
                current_step = 3
            elif not state.collection_created:
                current_step = 2
            else:
                current_step = state.last_step_completed

            return WizardStatusResponse(
                wizard_completed=state.wizard_completed,
                docker_check_passed=docker_check,
                docker_services_started=docker_started,
                collection_created=state.collection_created,
                last_step_completed=state.last_step_completed,
                current_step=current_step,
            )
    except Exception as e:
        logger.error(f"Error getting wizard status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/startup-check", response_model=StartupCheckResponse)
def check_startup_requirements():
    """
    Perform comprehensive startup checks to determine if wizard is needed.
    """
    try:
        from searchium.core.telemetry import telemetry

        checker = get_startup_checker()
        result = checker.perform_all_checks()

        # If wizard hasn't been completed yet, auto-complete it (skip Docker wizard steps)
        if not result.wizard_reset.passed:
            try:
                with db_session() as db:
                    repo = WizardStateRepository(db)
                    state = repo.get_or_create()
                    repo.update_docker_check(True)
                    repo.update_docker_services(True)
                    if state.collection_created is None:
                        repo.update_collection_created(True)
                    repo.mark_completed()
                logger.info("Wizard auto-completed on first run (Docker not required)")
                result.wizard_reset = CheckDetail(passed=True, message="Wizard auto-completed")
            except Exception as e:
                logger.warning(f"Failed to auto-complete wizard: {e}")

        if result.needs_wizard:
            telemetry.capture_event(
                "wizard_started",
                {
                    "start_step": result.get_first_failed_step(),
                    "model_downloaded": result.model_downloaded.passed,
                    "collection_ready": result.collection_ready.passed,
                    "schema_current": result.schema_current.passed,
                },
            )

        return StartupCheckResponse(
            all_checks_passed=result.all_checks_passed,
            needs_wizard=result.needs_wizard,
            is_first_run=result.is_first_run,
            start_step=result.get_first_failed_step(),
            is_upgrade=False,
            checks={
                "model_downloaded": {
                    "passed": result.model_downloaded.passed,
                    "message": result.model_downloaded.message,
                },
                "collection_ready": {
                    "passed": result.collection_ready.passed,
                    "message": result.collection_ready.message,
                },
                "schema_current": {
                    "passed": result.schema_current.passed,
                    "message": result.schema_current.message,
                },
                "wizard_reset": {
                    "passed": result.wizard_reset.passed,
                    "message": result.wizard_reset.message,
                },
            },
        )
    except Exception as e:
        logger.error(f"Error performing startup checks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/docker-check", response_model=DockerCheckResponse)
def check_docker():
    """Check if Docker is installed"""
    try:
        with db_session() as db:
            repo = WizardStateRepository(db)
            repo.update_docker_check(True)

        return DockerCheckResponse(
            available=True,
            command="docker",
            version="not required",
            has_gpu_hardware=False,
            has_nvidia_runtime=False,
            gpu_mode_enabled=False,
            error=None,
        )
    except Exception as e:
        logger.error(f"Error checking docker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/docker-images-check")
def check_docker_images():
    """Check if required docker images are present locally"""
    return {"success": True, "all_present": True, "missing": [], "present": []}


@router.get("/docker-pull")
def pull_docker_images():
    """Pull docker images with real progress updates via SSE"""
    import json

    def event_generator():
        yield "data: " + json.dumps({"status": "complete", "success": True, "message": "Docker not required"}) + "\n\n"

    from starlette.responses import StreamingResponse
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/docker-start", response_model=DockerStartResponse)
def start_docker_services():
    """Start docker-compose services"""
    with db_session() as db:
        repo = WizardStateRepository(db)
        repo.update_docker_services(True)
        repo.update_last_step(1)
    return DockerStartResponse(success=True, message="Docker not required", error=None)


@router.get("/docker-status", response_model=DockerStatusResponse)
def get_docker_status():
    """Get status of docker-compose services"""
    with db_session() as db:
        repo = WizardStateRepository(db)
        repo.update_docker_services(True)
    return DockerStatusResponse(
        success=True,
        running=True,
        healthy=True,
        services=[],
        error=None,
    )


@router.get("/docker-logs")
def stream_docker_logs():
    """Stream docker-compose logs via Server-Sent Events"""
    import json

    def event_generator():
        yield f"data: {json.dumps({'log': 'Docker not required', 'timestamp': 0})}\n\n"

    return sse_response(event_generator())


class ModelStatusResponse(BaseModel):
    """Response model for model status"""

    exists: bool
    path: str
    files: list
    missing_files: list


@router.get("/model-status", response_model=ModelStatusResponse)
def get_model_status():
    """Check if embedding model is already downloaded"""
    try:
        from searchium.services.model_downloader import get_model_downloader

        downloader = get_model_downloader()
        status = downloader.check_model_exists()

        return ModelStatusResponse(
            exists=status["exists"],
            path=status["path"],
            files=status["files"],
            missing_files=status["missing_files"],
        )
    except Exception as e:
        logger.error(f"Error checking model status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model-download")
def download_model():
    """Download embedding model with progress updates via SSE"""
    import json

    from searchium.services.model_downloader import get_model_downloader

    downloader = get_model_downloader()

    def event_generator():
        """Generate SSE events from model download progress"""

        # First check if model already exists
        status = downloader.check_model_exists()
        if status["exists"]:
            yield (
                "data: "
                + json.dumps(
                    {
                        "status": "complete",
                        "message": "Model already downloaded",
                        "complete": True,
                        "progress_percent": 100,
                    }
                )
                + "\n\n"
            )
            return

        # Use a queue to collect progress events
        import queue
        import threading

        progress_queue = queue.Queue()
        download_complete = threading.Event()
        download_error = [None]  # Use list to allow modification in nested function

        def progress_callback(data: dict):
            """Callback for each progress event"""
            progress_queue.put(data)

        # Start download in background thread
        def do_download():
            try:
                from searchium.core.telemetry import telemetry

                logger.info("Starting model download...")
                start_time = time.time()
                result = downloader.download_model_with_progress(progress_callback)
                duration = time.time() - start_time
                logger.info(f"Model download completed: {result}")

                if not result.get("success"):
                    download_error[0] = result.get("error")
                else:
                    # Track successful model download
                    telemetry.capture_event(
                        "wizard_step_model_download_completed",
                        {
                            "success": True,
                            "duration_seconds": round(duration, 2),
                        },
                    )

                download_complete.set()
                progress_queue.put(None)  # Signal completion
            except Exception as e:
                logger.error(f"Model download error: {e}", exc_info=True)
                download_error[0] = str(e)
                download_complete.set()
                progress_queue.put(None)

        thread = threading.Thread(target=do_download, daemon=True)
        thread.start()

        # Stream progress events
        logger.info("Starting model download SSE stream...")
        while True:
            try:
                data = progress_queue.get(timeout=120.0)
                if data is None:  # Completion signal
                    if download_error[0]:
                        yield "data: " + json.dumps({"error": download_error[0]}) + "\n\n"
                    break
                yield "data: " + json.dumps({**data, "timestamp": time.time()}) + "\n\n"
            except queue.Empty:
                yield "data: " + json.dumps({"heartbeat": True}) + "\n\n"
            except Exception as e:
                logger.error(f"Error streaming model download: {e}")
                yield "data: " + json.dumps({"error": str(e)}) + "\n\n"
                break

    return sse_response(event_generator())


@router.post("/collection-create", response_model=CollectionCreateResponse)
def create_collection():
    """Create Typesense collection (non-blocking - runs in background)"""
    import threading

    def _create_collection_task():
        """Background task to create collection"""
        from searchium.core.telemetry import telemetry
        from searchium.services.service_manager import get_service_manager

        # Reset service state and clear logs for fresh start
        service_manager = get_service_manager()
        service_manager.reset_service_for_retry("typesense")

        try:
            typesense = get_typesense_client()

            # Initialize collection
            typesense.initialize_collection()

            # Check if collection is ready
            if typesense.collection_ready:
                # Update wizard state
                with db_session() as db:
                    repo = WizardStateRepository(db)
                    repo.update_collection_created(True)
                    repo.update_last_step(2)
                logger.info("Collection creation completed successfully")

                # Track successful collection creation
                telemetry.capture_event(
                    "wizard_step_collection_created",
                    {"success": True},
                )
            else:
                logger.error("Collection creation failed")

        except Exception as e:
            logger.error(f"Error creating collection: {e}", exc_info=True)
            telemetry.capture_exception(e)

    # Start the background thread
    thread = threading.Thread(target=_create_collection_task, daemon=True)
    thread.start()

    # Return immediately
    return CollectionCreateResponse(
        success=True,
        message="Collection creation started in background",
    )


@router.get("/collection-status", response_model=CollectionStatusResponse)
def get_collection_status():
    """Get status of Typesense collection"""
    try:
        typesense = get_typesense_client()

        # Check if collection exists
        # We explicitly check against Typesense instead of relying on the local flag
        ready = typesense.check_collection_exists()

        # Get document count if available
        doc_count = None
        if ready:
            try:
                result = typesense.get_stats()
                doc_count = result.get("totals", {}).get("indexed", 0)
            except Exception:
                pass

        return CollectionStatusResponse(
            exists=ready,
            ready=ready,
            document_count=doc_count,
        )
    except Exception as e:
        logger.error(f"Error getting collection status: {e}")
        return CollectionStatusResponse(
            exists=False,
            ready=False,
            error=str(e),
        )


@router.post("/database-upgrade", response_model=DatabaseUpgradeResponse)
def upgrade_database():
    """Run database migrations to upgrade to latest revision"""
    try:
        from searchium.services.database_migrations import get_migration_service

        service = get_migration_service()
        success, logs = service.run_upgrade()

        message = "Database upgrade completed successfully" if success else "Database upgrade failed"

        return DatabaseUpgradeResponse(
            success=success,
            message=message,
            logs=logs,
        )
    except Exception as e:
        logger.error(f"Error upgrading database: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restart-typesense")
def restart_typesense():
    """Restart Typesense - no-op, Docker not required"""
    return {"success": True, "message": "Docker not required"}

@router.get("/collection-logs")
def stream_collection_logs():
    """Stream Typesense collection logs via SSE"""

    import json

    def event_generator():
        """Generate SSE events from Typesense service manager logs"""
        try:
            from searchium.services.service_manager import get_service_manager
            service_manager = get_service_manager()
            logs = service_manager.get_service_logs("typesense")
            for log in logs:
                yield f"data: {json.dumps({'log': log.get('message', ''), 'timestamp': log.get('timestamp', time.time())})}\n\n"
            yield f"data: {json.dumps({'complete': True})}\n\n"
        except Exception as e:
            logger.error(f"Error streaming collection logs: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return sse_response(event_generator())

@router.post("/complete")
def complete_wizard():
    """Mark wizard as complete"""
    try:
        from searchium.core.telemetry import telemetry

        with db_session() as db:
            repo = WizardStateRepository(db)
            state = repo.get_or_create()
            repo.mark_completed()

            # Track wizard completion
            telemetry.capture_event(
                "wizard_completed",
                {
                    "total_steps": state.last_step_completed + 1,
                    "docker_check_passed": state.docker_check_passed,
                    "docker_services_started": state.docker_services_started,
                    "collection_created": state.collection_created,
                },
            )

            # Set user properties for segmentation
            from datetime import datetime

            from searchium.core.config import settings

            telemetry.set_user_properties(
                {
                    "first_install_version": settings.app_version,
                    "wizard_completed_at": datetime.utcnow().isoformat(),
                }
            )

        return {
            "success": True,
            "message": "Wizard completed successfully",
            "timestamp": int(time.time() * 1000),
        }
    except Exception as e:
        logger.error(f"Error completing wizard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
def reset_wizard():
    """Reset wizard state (for testing/debugging)"""
    try:
        with db_session() as db:
            repo = WizardStateRepository(db)
            repo.reset()

        return {
            "success": True,
            "message": "Wizard state reset successfully",
            "timestamp": int(time.time() * 1000),
        }
    except Exception as e:
        logger.error(f"Error resetting wizard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# App Container Startup Endpoints (Post-Wizard)
# ============================================================================


@router.post("/app-containers-start")
def start_app_containers():
    """Start Docker containers for the main app (after wizard is completed)."""
    return {
        "success": True,
        "message": "Docker not required",
        "timestamp": int(time.time() * 1000),
    }


@router.get("/app-containers-status")
def stream_app_containers_status():
    """Stream container startup status via SSE."""
    import json

    def event_generator():
        yield f"data: {json.dumps({'success': True, 'running': True, 'healthy': True, 'services': [], 'error': None, 'timestamp': time.time()})}\n\n"

    return sse_response(event_generator())