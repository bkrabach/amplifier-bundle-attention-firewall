"""Windows startup management for Attention Firewall client.

Provides functionality to:
- Install/uninstall as a startup task (runs at user login)
- Use Task Scheduler for reliable auto-start
- Preserve dev workflow (can still run manually, pull changes, restart)
"""

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Task Scheduler task name
TASK_NAME = "CortexAttentionFirewall"


def get_pythonw_path() -> Path | None:
    """Get path to pythonw.exe (windowless Python) in the current environment."""
    python_path = Path(sys.executable)
    pythonw = python_path.parent / "pythonw.exe"
    if pythonw.exists():
        return pythonw
    # Fall back to regular python if pythonw not found
    return python_path


def get_client_config_path() -> Path:
    """Get the default client config path."""
    return Path.home() / ".cortex" / "client.yaml"


def is_installed() -> bool:
    """Check if the startup task is installed."""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        logger.warning("schtasks not found - not on Windows?")
        return False


def get_task_status() -> dict:
    """Get detailed status of the startup task."""
    if not is_installed():
        return {"installed": False}

    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
            capture_output=True,
            text=True,
        )

        status = {"installed": True, "raw": result.stdout}

        # Parse key fields
        for line in result.stdout.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().lower().replace(" ", "_")
                value = value.strip()
                if key in ("status", "last_run_time", "next_run_time", "last_result"):
                    status[key] = value

        return status
    except Exception as e:
        return {"installed": True, "error": str(e)}


def install(
    server_url: str | None = None,
    config_path: Path | None = None,
    verbose: bool = False,
) -> bool:
    """Install Attention Firewall as a Windows startup task.

    Args:
        server_url: Cortex server URL (e.g., http://192.168.1.100:19420)
        config_path: Path to client.yaml config file
        verbose: Enable verbose logging

    Returns:
        True if installation succeeded
    """
    # Build the command to run
    pythonw = get_pythonw_path()
    if not pythonw:
        logger.error("Could not find Python executable")
        return False

    # Get the package directory (where attention_firewall is installed)
    # This ensures the task runs from the right directory
    package_dir = Path(__file__).parent.parent.parent  # src -> attention_firewall -> startup.py

    # Use cmd /c to set working directory before running
    # This ensures Python can find the module even without PYTHONPATH
    cmd_parts = [
        "cmd",
        "/c",
        f"cd /d {package_dir} &&",
        str(pythonw),
        "-m",
        "attention_firewall",
        "client",
    ]

    if server_url:
        cmd_parts.extend(["--server", server_url])

    if config_path:
        cmd_parts.extend(["--config", str(config_path)])
    elif get_client_config_path().exists():
        cmd_parts.extend(["--config", str(get_client_config_path())])

    if verbose:
        cmd_parts.append("--verbose")

    # Join into a single command string
    command = " ".join(cmd_parts)

    # Remove existing task if present
    if is_installed():
        uninstall()

    # Create the scheduled task
    # /SC ONLOGON - Run when user logs in
    # /F - Force create (overwrite if exists)
    # Note: Don't use /RL HIGHEST - requires admin to create the task
    try:
        result = subprocess.run(
            [
                "schtasks",
                "/Create",
                "/TN",
                TASK_NAME,
                "/TR",
                command,
                "/SC",
                "ONLOGON",
                "/F",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logger.info(f"Installed startup task: {TASK_NAME}")
            logger.info(f"Command: {command}")
            return True
        else:
            logger.error(f"Failed to create task: {result.stderr}")
            return False

    except FileNotFoundError:
        logger.error("schtasks not found - this only works on Windows")
        return False
    except Exception as e:
        logger.error(f"Failed to install startup task: {e}")
        return False


def uninstall() -> bool:
    """Remove the Attention Firewall startup task.

    Returns:
        True if uninstallation succeeded (or task didn't exist)
    """
    if not is_installed():
        logger.info("Startup task not installed, nothing to remove")
        return True

    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logger.info(f"Removed startup task: {TASK_NAME}")
            return True
        else:
            logger.error(f"Failed to remove task: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Failed to uninstall startup task: {e}")
        return False


def start_now() -> bool:
    """Start the task immediately (without waiting for next login).

    Returns:
        True if task was started successfully
    """
    if not is_installed():
        logger.error("Startup task not installed. Run 'install' first.")
        return False

    try:
        result = subprocess.run(
            ["schtasks", "/Run", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logger.info(f"Started task: {TASK_NAME}")
            return True
        else:
            logger.error(f"Failed to start task: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Failed to start task: {e}")
        return False


def stop() -> bool:
    """Stop the running task.

    Returns:
        True if task was stopped successfully
    """
    if not is_installed():
        return True

    try:
        result = subprocess.run(
            ["schtasks", "/End", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
        )

        # Return code 1 means task wasn't running, which is fine
        if result.returncode in (0, 1):
            logger.info(f"Stopped task: {TASK_NAME}")
            return True
        else:
            logger.error(f"Failed to stop task: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Failed to stop task: {e}")
        return False
