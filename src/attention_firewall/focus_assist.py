"""Focus Assist / Do Not Disturb detection for Windows.

Detects the current Focus Assist state so Cortex can work alongside it:
- When Focus Assist is ON: Windows suppresses banners, Cortex handles curation
- When Focus Assist is OFF: Normal notification flow
"""

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class FocusAssistState(Enum):
    """Windows Focus Assist states."""

    OFF = "off"  # All notifications shown normally
    PRIORITY_ONLY = "priority_only"  # Only priority notifications
    ALARMS_ONLY = "alarms_only"  # Only alarms (most restrictive)
    UNKNOWN = "unknown"  # Could not determine state


def _try_get_focus_assist_from_registry() -> FocusAssistState | None:
    """Try to get Focus Assist state from Windows registry."""
    try:
        import winreg  # type: ignore[import-not-found]

        # Focus Assist settings are stored in this registry path
        key_path = (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\CloudStore\Store"
            r"\DefaultAccount\Current\default$windows.immersive.quiethours\Data"
        )

        try:
            key = winreg.OpenKey(  # type: ignore[attr-defined]
                winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
                key_path,
                0,
                winreg.KEY_READ,  # type: ignore[attr-defined]
            )
            value, _ = winreg.QueryValueEx(key, "Data")  # type: ignore[attr-defined]
            winreg.CloseKey(key)  # type: ignore[attr-defined]

            # The Data blob contains the focus assist state
            # Byte at offset 15 indicates the mode:
            # 0 = Off, 1 = Priority Only, 2 = Alarms Only
            if len(value) > 15:
                mode_byte = value[15]
                if mode_byte == 0:
                    return FocusAssistState.OFF
                elif mode_byte == 1:
                    return FocusAssistState.PRIORITY_ONLY
                elif mode_byte == 2:
                    return FocusAssistState.ALARMS_ONLY

        except FileNotFoundError:
            # Key doesn't exist, Focus Assist is off
            return FocusAssistState.OFF
        except Exception as e:
            logger.debug(f"Registry read failed: {e}")

    except ImportError:
        logger.debug("winreg not available (non-Windows platform)")

    return None


def _try_get_focus_assist_from_powershell() -> FocusAssistState | None:
    """Try to get Focus Assist state from PowerShell."""
    try:
        import subprocess

        # Query Windows Focus Assist via PowerShell
        ps_script = (
            "(Get-ItemProperty -Path "
            "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings' "
            "-Name NOC_GLOBAL_SETTING_ALLOW_TOASTS_ABOVE_LOCK "
            "-ErrorAction SilentlyContinue).NOC_GLOBAL_SETTING_ALLOW_TOASTS_ABOVE_LOCK"
        )
        cmd = ["powershell", "-NoProfile", "-Command", ps_script]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        # This is a partial check - better than nothing
        if result.returncode == 0 and result.stdout.strip():
            return FocusAssistState.OFF  # Basic toasts enabled

    except Exception as e:
        logger.debug(f"PowerShell check failed: {e}")

    return None


def get_focus_assist_state() -> FocusAssistState:
    """Get the current Windows Focus Assist state.

    Returns:
        Current Focus Assist state, or UNKNOWN if cannot determine.
    """
    # Try registry first (fastest)
    state = _try_get_focus_assist_from_registry()
    if state is not None:
        return state

    # Fall back to PowerShell
    state = _try_get_focus_assist_from_powershell()
    if state is not None:
        return state

    return FocusAssistState.UNKNOWN


def is_focus_assist_active() -> bool:
    """Check if Focus Assist is currently active (blocking notifications).

    Returns:
        True if Focus Assist is on (priority_only or alarms_only)
    """
    state = get_focus_assist_state()
    return state in (FocusAssistState.PRIORITY_ONLY, FocusAssistState.ALARMS_ONLY)


def get_focus_assist_info() -> dict:
    """Get detailed Focus Assist information.

    Returns:
        Dict with state info and recommendations.
    """
    state = get_focus_assist_state()

    descriptions = {
        FocusAssistState.OFF: "Focus Assist is OFF - all notifications shown",
        FocusAssistState.PRIORITY_ONLY: (
            "Focus Assist: Priority Only - most notifications suppressed"
        ),
        FocusAssistState.ALARMS_ONLY: ("Focus Assist: Alarms Only - all notifications suppressed"),
        FocusAssistState.UNKNOWN: "Could not determine Focus Assist state",
    }

    recommendations = {
        FocusAssistState.OFF: (
            "Consider enabling Focus Assist for Cortex-curated notifications only"
        ),
        FocusAssistState.PRIORITY_ONLY: ("Perfect! Cortex will surface important notifications"),
        FocusAssistState.ALARMS_ONLY: (
            "Cortex notifications may be blocked - consider Priority Only mode"
        ),
        FocusAssistState.UNKNOWN: (
            "Unable to detect Focus Assist - notifications may be duplicated"
        ),
    }

    return {
        "state": state.value,
        "is_active": state in (FocusAssistState.PRIORITY_ONLY, FocusAssistState.ALARMS_ONLY),
        "description": descriptions.get(state, "Unknown state"),
        "recommendation": recommendations.get(state, ""),
    }
