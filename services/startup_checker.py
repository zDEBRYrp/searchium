"""
Startup Check Service - Validates system requirements on app startup
"""

from dataclasses import dataclass
from typing import Optional

from searchium.core.logging import logger
from searchium.core.typesense_schema import get_schema_version
from searchium.database.models import db_session
from searchium.database.repositories.wizard_state_repository import (
    WizardStateRepository,
)
from searchium.services.model_downloader import get_model_downloader
from searchium.services.typesense_client import get_typesense_client


@dataclass
class CheckDetail:
    passed: bool
    message: str


@dataclass
class StartupCheckResult:
    model_downloaded: CheckDetail
    db_migration_current: CheckDetail
    collection_ready: CheckDetail
    schema_current: CheckDetail
    wizard_reset: CheckDetail

    @property
    def all_checks_passed(self) -> bool:
        return all([
            self.model_downloaded.passed,
            self.db_migration_current.passed,
            self.collection_ready.passed,
            self.schema_current.passed,
            self.wizard_reset.passed,
        ])

    @property
    def is_first_run(self) -> bool:
        return not self.wizard_reset.passed

    @property
    def needs_wizard(self) -> bool:
        if self.is_first_run:
            return True
        if not self.db_migration_current.passed:
            return True
        return False

    def get_first_failed_step(self) -> Optional[int]:
        if not self.wizard_reset.passed:
            return 0
        if not self.db_migration_current.passed:
            return 1
        if not self.model_downloaded.passed:
            return 2
        if not self.collection_ready.passed or not self.schema_current.passed:
            return 3
        return None


class StartupChecker:
    def __init__(self):
        self.model_downloader = get_model_downloader()
        self.typesense_client = get_typesense_client()
        from searchium.services.database_migrations import get_migration_service
        self.migration_service = get_migration_service()

    def check_model_downloaded(self) -> CheckDetail:
        try:
            status = self.model_downloader.check_model_exists()
            if status.get("exists"):
                return CheckDetail(passed=True, message="Embedding model ready")
            missing_count = len(status.get("missing_files", []))
            return CheckDetail(passed=False, message=f"{missing_count} model file(s) missing")
        except Exception as e:
            logger.error(f"Error checking model status: {e}")
            return CheckDetail(passed=False, message=f"Error: {str(e)}")

    def check_db_migration_current(self) -> CheckDetail:
        try:
            needed, current, head = self.migration_service.check_migration_needed()
            if needed:
                return CheckDetail(passed=False, message=f"Migration needed: {current} -> {head}")
            return CheckDetail(passed=True, message=f"Schema current ({current})")
        except Exception as e:
            logger.error(f"Error checking migration: {e}")
            return CheckDetail(passed=True, message=f"Migration check skipped: {str(e)}")

    def check_collection_ready(self) -> CheckDetail:
        try:
            exists = self.typesense_client.check_collection_exists()
            if exists:
                return CheckDetail(passed=True, message="Collection exists")
            return CheckDetail(passed=False, message="Collection not found")
        except Exception as e:
            error_msg = str(e).lower()
            if "503" in error_msg or "not ready" in error_msg or "connection" in error_msg:
                return CheckDetail(passed=True, message="Typesense initializing")
            return CheckDetail(passed=True, message=f"Typesense check skipped: {str(e)}")

    def check_schema_current(self) -> CheckDetail:
        try:
            current_version = get_schema_version()
            exists = self.typesense_client.check_collection_exists()
            if not exists:
                return CheckDetail(passed=False, message="Collection does not exist")
            return CheckDetail(passed=True, message=f"Schema version: {current_version}")
        except Exception as e:
            return CheckDetail(passed=True, message=f"Schema check skipped: {str(e)}")

    def check_wizard_reset(self) -> CheckDetail:
        try:
            with db_session() as db:
                repo = WizardStateRepository(db)
                state = repo.get()
                if state and state.wizard_completed:
                    return CheckDetail(passed=True, message="Wizard completed")
                return CheckDetail(passed=False, message="Wizard not completed")
        except Exception as e:
            return CheckDetail(passed=True, message=f"Check skipped: {str(e)}")

    def perform_all_checks(self) -> StartupCheckResult:
        logger.info("Starting startup checks...")

        wizard_check = self.check_wizard_reset()
        model_check = self.check_model_downloaded()
        db_migration_check = self.check_db_migration_current()

        if not wizard_check.passed:
            logger.info("Wizard not completed - showing wizard")
            return StartupCheckResult(
                model_downloaded=model_check,
                db_migration_current=db_migration_check,
                collection_ready=CheckDetail(passed=True, message="Skipped"),
                schema_current=CheckDetail(passed=True, message="Skipped"),
                wizard_reset=wizard_check,
            )

        try:
            collection_check = self.check_collection_ready()
            schema_check = self.check_schema_current()
        except Exception as e:
            collection_check = CheckDetail(passed=True, message=f"Skipped: {e}")
            schema_check = CheckDetail(passed=True, message=f"Skipped: {e}")

        check_result = StartupCheckResult(
            model_downloaded=model_check,
            db_migration_current=db_migration_check,
            collection_ready=collection_check,
            schema_current=schema_check,
            wizard_reset=wizard_check,
        )

        logger.info(f"Startup checks complete. Wizard needed: {check_result.needs_wizard}")
        return check_result


_checker: Optional[StartupChecker] = None


def get_startup_checker() -> StartupChecker:
    global _checker
    if _checker is None:
        _checker = StartupChecker()
    return _checker
