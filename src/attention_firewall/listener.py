"""Windows notification listener using pywinrt.

Captures ALL toast notifications system-wide via UserNotificationListener API.
Requires Windows 10 Anniversary Update+ (build 14393+).
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


class NotificationData:
    """Normalized notification data."""
    
    def __init__(
        self,
        notification_id: str,
        app_id: str,
        title: str,
        body: str,
        timestamp: str,
        sender: str | None = None,
        conversation_hint: str | None = None,
    ):
        self.notification_id = notification_id
        self.app_id = app_id
        self.title = title
        self.body = body
        self.timestamp = timestamp
        self.sender = sender
        self.conversation_hint = conversation_hint
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "app_id": self.app_id,
            "title": self.title,
            "body": self.body,
            "timestamp": self.timestamp,
            "sender": self.sender,
            "conversation_hint": self.conversation_hint,
        }


def _try_import_winrt():
    """Try to import winrt modules, return None if not available."""
    try:
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )
        from winrt.windows.ui.notifications import KnownNotificationBindings
        return {
            "UserNotificationListener": UserNotificationListener,
            "UserNotificationListenerAccessStatus": UserNotificationListenerAccessStatus,
            "KnownNotificationBindings": KnownNotificationBindings,
        }
    except ImportError:
        return None


class WindowsNotificationListener:
    """Listens for Windows toast notifications.
    
    Uses UserNotificationListener API via pywinrt to capture notifications
    from all apps. Notifications are normalized and passed to a callback.
    
    Note: This only works on Windows. On other platforms, a mock listener
    can be used for testing.
    """
    
    def __init__(
        self,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        """Initialize the listener.
        
        Args:
            queue: Async queue to put notifications into
            loop: Event loop for thread-safe queue operations
        """
        self.queue = queue
        self.loop = loop or asyncio.get_event_loop()
        self._listener = None
        self._running = False
        self._winrt = _try_import_winrt()
        
        if self._winrt is None:
            logger.warning(
                "winrt modules not available - running in mock mode. "
                "Install winrt-Windows.UI.Notifications for real notification capture."
            )
    
    @property
    def is_available(self) -> bool:
        """Check if notification listening is available on this platform."""
        return self._winrt is not None
    
    async def request_access(self) -> bool:
        """Request permission to listen to notifications.
        
        Returns True if permission granted, False otherwise.
        Must be called before start().
        """
        if not self._winrt:
            logger.info("Mock mode: Simulating access granted")
            return True
        
        UserNotificationListener = self._winrt["UserNotificationListener"]
        AccessStatus = self._winrt["UserNotificationListenerAccessStatus"]
        
        # pywinrt static class pattern: the class itself is the singleton
        # Methods need the class passed as 'self'
        self._listener = UserNotificationListener
        
        # Request access - pass class as self for static class pattern
        status = await UserNotificationListener.request_access_async(UserNotificationListener)
        
        if status == AccessStatus.ALLOWED:
            logger.info("Notification access granted")
            return True
        else:
            logger.error(f"Notification access denied: {status}")
            return False
    
    def _extract_notification_data(self, notif) -> NotificationData | None:
        """Extract normalized data from a Windows notification object."""
        try:
            KnownBindings = self._winrt["KnownNotificationBindings"]
            
            # Get app info
            app_id = "Unknown"
            if hasattr(notif, "app_info") and notif.app_info:
                try:
                    app_id = notif.app_info.display_info.display_name
                except Exception:
                    pass
            
            # Get text content from toast binding
            title = ""
            body = ""
            
            try:
                # Handle both API styles: get_binding/GetBinding, get_toast_generic/ToastGeneric
                toast_generic = (
                    KnownBindings.ToastGeneric if hasattr(KnownBindings, "ToastGeneric")
                    else KnownBindings.get_toast_generic()
                )
                if hasattr(notif.notification.visual, "GetBinding"):
                    binding = notif.notification.visual.GetBinding(toast_generic)
                else:
                    binding = notif.notification.visual.get_binding(toast_generic)
                if binding:
                    # Handle both API styles
                    if hasattr(binding, "GetTextElements"):
                        texts = list(binding.GetTextElements())
                    else:
                        texts = list(binding.get_text_elements())
                    if texts:
                        # Text property might be Text or text
                        def get_text(t):
                            return t.Text if hasattr(t, "Text") else t.text
                        title = get_text(texts[0]) if texts else ""
                        body = " ".join(get_text(t) for t in texts[1:]) if len(texts) > 1 else ""
            except Exception as e:
                logger.debug(f"Could not extract text: {e}")
            
            # Get timestamp
            timestamp = datetime.now().isoformat()
            try:
                if hasattr(notif, "creation_time"):
                    timestamp = notif.creation_time.isoformat()
            except Exception:
                pass
            
            # Try to extract sender (heuristic: first line of title often has sender)
            sender = self._extract_sender(app_id, title, body)
            
            return NotificationData(
                notification_id=str(notif.id) if hasattr(notif, "id") else str(id(notif)),
                app_id=app_id,
                title=title,
                body=body,
                timestamp=timestamp,
                sender=sender,
            )
            
        except Exception as e:
            logger.error(f"Error extracting notification data: {e}")
            return None
    
    def _extract_sender(self, app_id: str, title: str, body: str) -> str | None:
        """Try to extract sender name from notification content.
        
        Different apps format their notifications differently:
        - Teams: Title is often the sender name or channel
        - WhatsApp: Title is sender or group name
        - Outlook: Title might be "New mail from [sender]"
        """
        # Simple heuristic: use title as sender hint for messaging apps
        messaging_apps = ["teams", "whatsapp", "slack", "discord", "telegram"]
        app_lower = app_id.lower()
        
        if any(app in app_lower for app in messaging_apps):
            # Title is often the sender/channel
            return title if title else None
        
        # For email apps, try to extract from "from [sender]" pattern
        if "outlook" in app_lower or "mail" in app_lower:
            # Check for "from X" pattern in title or body
            for text in [title, body]:
                if "from " in text.lower():
                    # Extract name after "from"
                    idx = text.lower().find("from ")
                    if idx >= 0:
                        sender_part = text[idx + 5:].split()[0:3]  # Take up to 3 words
                        return " ".join(sender_part)
        
        return None
    
    def _on_notification_changed(self, sender, args):
        """Callback when a notification is added or removed."""
        if not self._running:
            return
        
        try:
            # Only process additions
            if hasattr(args, "change_kind"):
                from winrt.windows.ui.notifications import NotificationKinds
                # We only care about new notifications, not removals
                pass
            
            # Get the notification - handle both API styles
            notif_id = args.UserNotificationId if hasattr(args, "UserNotificationId") else args.user_notification_id
            if hasattr(self._listener, "GetNotification"):
                notif = self._listener.GetNotification(notif_id)
            else:
                notif = self._listener.get_notification(notif_id)
            if notif is None:
                return
            
            # Extract and normalize
            data = self._extract_notification_data(notif)
            if data is None:
                return
            
            logger.debug(f"Notification received: {data.app_id} - {data.title}")
            
            # Thread-safe queue put
            asyncio.run_coroutine_threadsafe(
                self.queue.put(data),
                self.loop
            )
            
        except Exception as e:
            logger.error(f"Error processing notification: {e}")
    
    async def start(self) -> None:
        """Start listening for notifications."""
        if self._running:
            return
        
        if not self._winrt:
            logger.info("Mock mode: Listener started (no real notifications)")
            self._running = True
            return
        
        if self._listener is None:
            granted = await self.request_access()
            if not granted:
                raise PermissionError("Notification access not granted")
        
        # Register for notification changes - handle both API styles
        if hasattr(self._listener, "add_NotificationChanged"):
            self._listener.add_NotificationChanged(self._on_notification_changed)
        else:
            self._listener.add_notification_changed(self._on_notification_changed)
        self._running = True
        logger.info("Windows notification listener started")
    
    async def stop(self) -> None:
        """Stop listening for notifications."""
        self._running = False
        # Note: pywinrt doesn't have a clean way to remove handlers
        logger.info("Windows notification listener stopped")
    
    async def get_current_notifications(self) -> list[NotificationData]:
        """Get all current notifications in the notification center."""
        if not self._winrt or not self._listener:
            return []
        
        try:
            from winrt.windows.ui.notifications import NotificationKinds
            
            # Handle both API styles
            toast_kind = NotificationKinds.Toast if hasattr(NotificationKinds, "Toast") else NotificationKinds.TOAST
            if hasattr(self._listener, "GetNotificationsAsync"):
                notifications = await self._listener.GetNotificationsAsync(toast_kind)
            else:
                notifications = await self._listener.get_notifications_async(toast_kind)
            
            result = []
            for notif in notifications:
                data = self._extract_notification_data(notif)
                if data:
                    result.append(data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting current notifications: {e}")
            return []


class MockNotificationListener:
    """Mock listener for testing on non-Windows platforms."""
    
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        self._running = False
    
    @property
    def is_available(self) -> bool:
        return True
    
    async def request_access(self) -> bool:
        return True
    
    async def start(self) -> None:
        self._running = True
        logger.info("Mock notification listener started")
    
    async def stop(self) -> None:
        self._running = False
        logger.info("Mock notification listener stopped")
    
    async def inject_test_notification(
        self,
        app_id: str = "Test App",
        title: str = "Test Notification",
        body: str = "This is a test notification",
        sender: str | None = None,
    ) -> None:
        """Inject a test notification for development/testing."""
        data = NotificationData(
            notification_id=str(id(self)),
            app_id=app_id,
            title=title,
            body=body,
            timestamp=datetime.now().isoformat(),
            sender=sender,
        )
        await self.queue.put(data)
    
    async def get_current_notifications(self) -> list[NotificationData]:
        return []


def create_listener(
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop | None = None,
) -> WindowsNotificationListener | MockNotificationListener:
    """Create appropriate listener for the current platform."""
    winrt = _try_import_winrt()
    
    if winrt is not None:
        return WindowsNotificationListener(queue, loop)
    else:
        logger.warning("Using mock listener (pywinrt not available)")
        return MockNotificationListener(queue)
