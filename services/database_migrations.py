import io
import logging
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

import searchium
from searchium.database.models.base import engine

logger = logging.getLogger(__name__)


class DatabaseMigrationService:
    def __init__(self):
        self.package_root = Path(searchium.__file__).parent
        self.project_root = self.package_root.parent

        # Find alembic.ini
        possible_paths = [
            self.package_root / "alembic.ini",
            self.project_root / "alembic.ini",
        ]

        self.alembic_ini_path = None
        for path in possible_paths:
            if path.exists():
                self.alembic_ini_path = path
                break

        self.alembic_cfg = None
        if self.alembic_ini_path:
            try:
                self.alembic_cfg = Config(str(self.alembic_ini_path))
                self.alembic_cfg.attributes["configure_logger"] = False
            except Exception as e:
                logger.warning(f"Failed to load alembic config: {e}")

    def _is_available(self) -> bool:
        return self.alembic_cfg is not None

    def get_current_revision(self) -> Optional[str]:
        try:
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                return context.get_current_revision()
        except Exception as e:
            logger.error(f"Error getting current revision: {e}")
            return None

    def get_head_revision(self) -> Optional[str]:
        if not self._is_available():
            return self.get_current_revision()
        try:
            script = ScriptDirectory.from_config(self.alembic_cfg)
            head = script.get_current_head()
            return head
        except Exception as e:
            logger.error(f"Error getting head revision: {e}")
            return self.get_current_revision()

    def check_migration_needed(self) -> Tuple[bool, Optional[str], Optional[str]]:
        if not self._is_available():
            return False, None, None
        current = self.get_current_revision()
        head = self.get_head_revision()
        if current is None or head is None:
            return False, current, head
        return current != head, current, head

    def run_upgrade(self) -> Tuple[bool, List[str]]:
        if not self._is_available():
            return False, ["Alembic configuration not found"]

        log_capture = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = log_capture
        sys.stderr = log_capture

        root_logger = logging.getLogger()
        stream_handler = logging.StreamHandler(log_capture)
        stream_handler.setLevel(logging.INFO)
        root_logger.addHandler(stream_handler)

        success = False
        try:
            logger.info("Starting database upgrade to head...")
            command.upgrade(self.alembic_cfg, "head")
            logger.info("Database upgrade completed successfully.")
            success = True
        except Exception as e:
            logger.error(f"Database upgrade failed: {e}")
            print(f"Error: {e}")
            success = False
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            root_logger.removeHandler(stream_handler)

        return success, log_capture.getvalue().splitlines()


_migration_service: Optional[DatabaseMigrationService] = None


def get_migration_service() -> DatabaseMigrationService:
    global _migration_service
    if _migration_service is None:
        _migration_service = DatabaseMigrationService()
    return _migration_service
