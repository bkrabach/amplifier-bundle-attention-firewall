"""Windows toast notification sender.

Raises agent-branded notifications to surface important items to the user.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _try_import_winrt():
    """Try to import winrt modules for sending toasts."""
    try:
        from winrt.windows.ui.notifications import (
            ToastNotificationManager,
            ToastNotification,
            ToastTemplateType,
        )
        from winrt.windows.data.xml.dom import XmlDocument
        return {
            "ToastNotificationManager": ToastNotificationManager,
            "ToastNotification": ToastNotification,
            "ToastTemplateType": ToastTemplateType,
            "XmlDocument": XmlDocument,
        }
    except ImportError:
        return None


class ToastSender:
    """Sends Windows toast notifications.
    
    Uses the Windows Toast Notification API to display agent-branded
    notifications with customizable content and urgency levels.
    """
    
    # App identifier for our notifications
    APP_ID = "Attention Firewall"
    
    def __init__(self):
        self._winrt = _try_import_winrt()
        
        if self._winrt is None:
            logger.warning(
                "winrt modules not available - toasts will be logged only. "
                "Install winrt-Windows.UI.Notifications for real toast support."
            )
    
    @property
    def is_available(self) -> bool:
        """Check if toast sending is available."""
        return self._winrt is not None
    
    def _build_toast_xml(
        self,
        title: str,
        body: str,
        urgency: str = "normal",
        rationale: str | None = None,
        app_source: str | None = None,
    ) -> str:
        """Build toast notification XML."""
        # Escape XML special characters
        def escape(s: str) -> str:
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;")
            )
        
        # Add attribution if provided
        attribution = ""
        if rationale:
            attribution = f'<text placement="attribution">{escape(rationale)}</text>'
        
        # Build the toast XML
        # Using ToastGeneric template for flexible layout
        xml = f"""
        <toast activationType="protocol" scenario="{"urgent" if urgency == "high" else "default"}">
            <visual>
                <binding template="ToastGeneric">
                    <text>{escape(title)}</text>
                    <text>{escape(body)}</text>
                    {attribution}
                </binding>
            </visual>
            <audio silent="{str(urgency == 'low').lower()}" />
        </toast>
        """
        
        return xml.strip()
    
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
        if not self._winrt:
            # Log the notification that would have been sent
            urgency_emoji = {"low": "📩", "normal": "📬", "high": "🚨"}.get(urgency, "📬")
            logger.info(
                f"{urgency_emoji} [TOAST] {title}\n"
                f"   {body}\n"
                f"   Rationale: {rationale or 'N/A'}"
            )
            return True
        
        try:
            ToastNotificationManager = self._winrt["ToastNotificationManager"]
            ToastNotification = self._winrt["ToastNotification"]
            XmlDocument = self._winrt["XmlDocument"]
            
            # Build XML
            xml_string = self._build_toast_xml(
                title=title,
                body=body,
                urgency=urgency,
                rationale=rationale,
                app_source=app_source,
            )
            
            # Parse XML
            doc = XmlDocument()
            doc.load_xml(xml_string)
            
            # Create and show notification
            notifier = ToastNotificationManager.create_toast_notifier(self.APP_ID)
            toast = ToastNotification(doc)
            
            notifier.show(toast)
            
            logger.debug(f"Toast sent: {title}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send toast: {e}")
            return False
    
    async def send_summary(
        self,
        title: str = "Notification Summary",
        items: list[dict[str, Any]] = None,
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
