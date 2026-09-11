"""
Utility to read app info from pyproject.toml
"""

import os
import tomllib as toml  # For Python 3.11 and above


def get_app_info():
    """
    Reads pyproject.toml and returns a dictionary with app info.
    """
    try:
        # 1. Try to read pyproject.toml directly (Dev mode - Source of Truth)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        pyproject_path = os.path.join(current_dir, "..", "..", "pyproject.toml")

        if os.path.exists(pyproject_path):
            with open(pyproject_path, "rb") as f:
                pyproject_data = toml.load(f)

            project_data = pyproject_data.get("project", {})
            return {
                "name": project_data.get("name", "searchium"),
                "version": project_data.get("version", "0.0.0"),
                "description": project_data.get("description", "Searchium"),
            }

        # 2. Fallback to installed package metadata
        from importlib.metadata import PackageNotFoundError, version

        try:
            pkg_version = version("searchium")
            return {
                "name": "searchium",
                "version": pkg_version,
                "description": "Searchium",
            }
        except PackageNotFoundError:
            pass
        except Exception:
            pass

        return {"name": "searchium", "version": "0.0.0-error", "description": "Searchium"}
    except Exception as e:
        print(f"Error reading app info: {e}")
        return {"name": "searchium", "version": "0.0.0-error", "description": "Searchium"}


_app_info = get_app_info()


def get_app_name() -> str:
    """Get app name"""
    return _app_info["name"]


def get_app_version() -> str:
    """Get app version"""
    return _app_info["version"]


def get_app_description() -> str:
    """Get app description"""
    return _app_info["description"]
