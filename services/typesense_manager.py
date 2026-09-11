"""
Typesense Manager - Downloads and manages standalone Typesense server
"""

import os
import platform
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Optional

from searchium.core.logging import logger

TYPESENSE_VERSION = "29.0"
TYPESENSE_API_KEY = "xyz-typesense-key"

DOWNLOAD_URLS = {
    "Linux": f"https://github.com/typesense/typesense/releases/download/v{TYPESENSE_VERSION}/typesense-server-linux-amd64-v{TYPESENSE_VERSION}.tar.gz",
    "Darwin": f"https://github.com/typesense/typesense/releases/download/v{TYPESENSE_VERSION}/typesense-server-linux-amd64-v{TYPESENSE_VERSION}.tar.gz",
}


class TypesenseManager:
    """Manages standalone Typesense server process"""

    def __init__(self):
        from searchium.core.paths import app_paths
        from searchium.core.config import settings

        self.data_dir = app_paths.typesense_data_dir
        self.bin_dir = app_paths.data_dir / "typesense-bin"
        self.process: Optional[subprocess.Popen] = None
        self.host = settings.typesense_host
        self.port = settings.typesense_port
        self.api_key = settings.typesense_api_key

    def _get_binary_path(self) -> Path:
        if platform.system() == "Windows":
            return self.bin_dir / "typesense-server.exe"
        return self.bin_dir / "typesense-server"

    def is_platform_supported(self) -> bool:
        """Check if Typesense has a native binary for this platform"""
        return platform.system() in DOWNLOAD_URLS

    def is_installed(self) -> bool:
        return self._get_binary_path().exists()

    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def download(self, progress_callback=None) -> bool:
        """Download Typesense binary"""
        system = platform.system()
        url = DOWNLOAD_URLS.get(system)
        if not url:
            logger.warning(f"No native Typesense binary for {system} - search will be unavailable")
            return False

        self.bin_dir.mkdir(parents=True, exist_ok=True)
        zip_path = self.bin_dir / "typesense.zip"

        try:
            import httpx

            logger.info(f"Downloading Typesense {TYPESENSE_VERSION}...")
            if progress_callback:
                progress_callback({"message": f"Downloading Typesense {TYPESENSE_VERSION}...", "progress": 0})

            with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(zip_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback({
                                "message": f"Downloading Typesense... {downloaded // (1024*1024)}MB / {total // (1024*1024)}MB",
                                "progress": int(downloaded / total * 100),
                            })

            if progress_callback:
                progress_callback({"message": "Extracting Typesense...", "progress": 95})

            logger.info("Extracting Typesense...")
            if system == "Windows":
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(self.bin_dir)
            else:
                import tarfile
                with tarfile.open(zip_path, "r:gz") as tf:
                    tf.extractall(self.bin_dir)

            zip_path.unlink(missing_ok=True)

            binary = self._get_binary_path()
            if not binary.exists():
                logger.error(f"Typesense binary not found after extraction at {binary}")
                return False

            if system != "Windows":
                os.chmod(str(binary), 0o755)

            logger.info(f"Typesense installed at {binary}")
            if progress_callback:
                progress_callback({"message": "Typesense ready", "progress": 100})
            return True

        except Exception as e:
            logger.error(f"Failed to download Typesense: {e}")
            zip_path.unlink(missing_ok=True)
            return False

    def start(self) -> bool:
        """Start Typesense server"""
        if self.is_running():
            logger.info("Typesense already running")
            return True

        if not self.is_platform_supported():
            logger.warning(f"Typesense has no native binary for {platform.system()} - search unavailable")
            return False

        binary = self._get_binary_path()
        if not binary.exists():
            logger.info("Typesense not found, downloading...")
            if not self.download():
                return False

        self.data_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(binary),
            f"--data-dir={self.data_dir}",
            f"--api-key={self.api_key}",
            f"--listen-port={self.port}",
            "--snapshot-interval-seconds=60",
            "--log-type=stderr",
        ]

        try:
            logger.info(f"Starting Typesense on port {self.port}...")
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
            )

            time.sleep(2)

            if self.process.poll() is not None:
                stderr = self.process.stderr.read().decode(errors="replace")
                logger.error(f"Typesense exited immediately: {stderr}")
                return False

            logger.info(f"Typesense started (PID: {self.process.pid})")
            return True

        except Exception as e:
            logger.error(f"Failed to start Typesense: {e}")
            return False

    def stop(self):
        """Stop Typesense server"""
        if self.process and self.is_running():
            logger.info("Stopping Typesense...")
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Typesense didn't stop gracefully, killing...")
                self.process.kill()
                self.process.wait(timeout=5)
            logger.info("Typesense stopped")
        self.process = None

    def wait_until_ready(self, timeout: int = 30) -> bool:
        """Wait until Typesense is accepting connections"""
        import httpx

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_running():
                logger.error("Typesense process died")
                return False
            try:
                r = httpx.get(f"http://{self.host}:{self.port}/health", timeout=2)
                if r.status_code == 200:
                    logger.info("Typesense is ready")
                    return True
            except Exception:
                pass
            time.sleep(0.5)

        logger.error(f"Typesense not ready after {timeout}s")
        return False


_manager: Optional[TypesenseManager] = None


def get_typesense_manager() -> TypesenseManager:
    global _manager
    if _manager is None:
        _manager = TypesenseManager()
    return _manager
