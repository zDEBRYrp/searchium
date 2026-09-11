"""
GPU Detection Utility

Detects NVIDIA GPU availability for Typesense GPU mode.
"""

import logging
import platform
import subprocess
from typing import Dict

logger = logging.getLogger(__name__)


def is_nvidia_gpu_available() -> bool:
    """
    Check if an NVIDIA GPU is available on the system.

    Returns:
        bool: True if nvidia-smi command succeeds, False otherwise
    """
    try:
        nvidia_smi_cmd = "nvidia-smi.exe" if platform.system() == "Windows" else "nvidia-smi"

        result = subprocess.run(
            [nvidia_smi_cmd],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        if result.returncode == 0:
            logger.debug("NVIDIA GPU detected via nvidia-smi")
            return True
        else:
            logger.debug(f"nvidia-smi failed with return code {result.returncode}")
            return False

    except FileNotFoundError:
        logger.debug("nvidia-smi not found - no NVIDIA GPU drivers installed")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("nvidia-smi command timed out")
        return False
    except Exception as e:
        logger.debug(f"Failed to check for NVIDIA GPU: {type(e).__name__}: {e}")
        return False


def should_use_gpu_mode() -> bool:
    """
    Determine if GPU mode should be enabled for Typesense.

    Respects FILEBRAIN_GPU_MODE environment variable:
    - 'auto' (default): Auto-detect GPU availability
    - 'force-gpu': Always return True
    - 'force-cpu': Always return False

    Returns:
        bool: True if GPU mode should be used, False otherwise
    """
    from searchium.core.config import settings

    gpu_mode = settings.gpu_mode.lower()

    if gpu_mode == "force-gpu":
        logger.info("GPU mode forced via FILEBRAIN_GPU_MODE=force-gpu")
        return True
    elif gpu_mode == "force-cpu":
        logger.info("CPU mode forced via FILEBRAIN_GPU_MODE=force-cpu")
        return False
    elif gpu_mode == "auto":
        has_gpu = is_nvidia_gpu_available()
        if has_gpu:
            logger.info("GPU mode enabled - NVIDIA GPU detected")
            return True
        else:
            logger.debug("GPU mode disabled - no NVIDIA GPU detected")
            return False
    else:
        logger.warning(f"Invalid FILEBRAIN_GPU_MODE='{gpu_mode}', defaulting to auto-detect")
        return is_nvidia_gpu_available()


def get_gpu_info() -> Dict[str, bool]:
    """
    Get detailed GPU availability information for telemetry and debugging.

    Returns:
        dict: Dictionary with GPU detection results
    """
    return {
        "has_gpu_hardware": is_nvidia_gpu_available(),
        "gpu_mode_enabled": should_use_gpu_mode(),
    }
