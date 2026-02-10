"""Windows toast notification sender.

Raises agent-branded notifications to surface important items to the user.
Uses PowerShell for reliable cross-version Windows support.
"""

import logging
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _escape_powershell(s: str) -> str:
    """Escape a string for use in PowerShell."""
    # Escape backticks, dollars, and quotes
    return s.replace("`", "``").replace('"', '`"').replace("$", "`$")


def _escape_xml(s: str) -> str:
    """Escape XML special characters."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


class ToastSender:
    """Sends Windows toast notifications.

    Uses PowerShell and the Windows Toast Notification API to display
    agent-branded notifications with customizable content and urgency levels.
    """

    # App identifier for our notifications
    APP_ID = "Cortex"

    def __init__(self):
        self._is_windows = sys.platform == "win32"
        if not self._is_windows:
            logger.warning("Not running on Windows - toasts will be logged only")

    @property
    def is_available(self) -> bool:
        """Check if toast sending is available."""
        return self._is_windows

    async def send(
        self,
        title: str,
        body: str,
        urgency: str = "normal",
        rationale: str | None = None,
        app_source: str | None = None,
        actions: list[dict[str, str]] | None = None,
    ) -> bool:
        """Send a toast notification.

        Args:
            title: Notification title (brief, include source app/sender)
            body: Notification body text
            urgency: "low", "normal", or "high"
            rationale: Brief explanation of why this was surfaced
            app_source: Original app that generated this notification
            actions: List of action buttons (not implemented yet)

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._is_windows:
            # Log the notification that would have been sent
            urgency_emoji = {"low": "📩", "normal": "📬", "high": "🚨"}.get(
                urgency, "📬"
            )
            logger.info(
                f"{urgency_emoji} [TOAST] {title}\n"
                f"   {body}\n"
                f"   Rationale: {rationale or 'N/A'}"
            )
            return True

        try:
            return self._send_via_powershell(
                title=title,
                body=body,
                urgency=urgency,
                rationale=rationale,
                app_source=app_source,
            )
        except Exception as e:
            logger.error(f"Failed to send toast: {e}")
            return False

    def _send_via_powershell(
        self,
        title: str,
        body: str,
        urgency: str = "normal",
        rationale: str | None = None,
        app_source: str | None = None,
    ) -> bool:
        """Send toast using PowerShell (reliable cross-version approach)."""
        # Build attribution text
        attribution = ""
        if rationale:
            attribution_xml = (
                f'<text placement="attribution">{_escape_xml(rationale)}</text>'
            )
            attribution = attribution_xml

        # Determine scenario based on urgency
        scenario = "urgent" if urgency == "high" else "default"
        silent = "true" if urgency == "low" else "false"

        # Build the toast XML
        toast_xml = f"""
<toast activationType="protocol" scenario="{scenario}">
    <visual>
        <binding template="ToastGeneric">
            <text>{_escape_xml(title)}</text>
            <text>{_escape_xml(body)}</text>
            {attribution}
        </binding>
    </visual>
    <audio silent="{silent}" />
</toast>
""".strip()

        # PowerShell script to show the toast
        # This approach works on Windows 10/11 without BurntToast
        ps_script = f"""
$ErrorActionPreference = 'Stop'

# Load WinRT assemblies
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]

# Create XML document
$xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
$xml.LoadXml(@'
{toast_xml}
'@)

# Create and show notification
$appId = '{self.APP_ID}'
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId)
$notifier.Show($toast)
"""

        # Run PowerShell (hidden - no console window)
        # CREATE_NO_WINDOW flag prevents the PowerShell window from flashing
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags,
        )

        if result.returncode != 0:
            logger.error(f"PowerShell toast failed: {result.stderr}")
            return False

        logger.debug(f"Toast sent via PowerShell: {title}")
        return True

    async def send_summary(
        self,
        title: str = "Notification Summary",
        items: list[dict[str, Any]] | None = None,
        timeframe: str = "last hour",
    ) -> bool:
        """Send a summary notification.

        Args:
            title: Summary title
            items: List of notification items to summarize
            timeframe: Time period covered
        """
        items = items or []

        if not items:
            body = f"No notifications in the {timeframe}."
        else:
            # Group by app
            by_app: dict[str, int] = {}
            for item in items:
                app = item.get("app_id", "Unknown")
                by_app[app] = by_app.get(app, 0) + 1

            # Build summary body
            parts = [f"{count} from {app}" for app, count in by_app.items()]
            body = f"{len(items)} notifications: " + ", ".join(parts)

        return await self.send(
            title=title,
            body=body,
            urgency="low",
            rationale=f"Summary for {timeframe}",
        )


# Convenience function for quick access
async def send_toast(
    title: str,
    body: str,
    urgency: str = "normal",
    rationale: str | None = None,
    **kwargs,
) -> bool:
    """Send a toast notification (convenience wrapper)."""
    sender = ToastSender()
    return await sender.send(
        title=title,
        body=body,
        urgency=urgency,
        rationale=rationale,
        **kwargs,
    )
