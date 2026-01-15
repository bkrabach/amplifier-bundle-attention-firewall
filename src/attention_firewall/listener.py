"""Windows notification listener using pywinrt.

Captures ALL toast notifications system-wide via UserNotificationListener API.
Requires Windows 10 Anniversary Update+ (build 14393+).
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

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
        from winrt.windows.ui.notifications import KnownNotificationBindings
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )

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

        # pywinrt 2.0+: static properties are accessed as lowercase attributes
        self._listener = UserNotificationListener.current

        # Request access
        status = await self._listener.request_access_async()

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

            # Get app info - some notifications throw E_NOTIMPL when accessing properties
            app_id = "Unknown"
            if hasattr(notif, "app_info"):
                try:
                    if notif.app_info and hasattr(notif.app_info, "display_info"):
                        app_id = notif.app_info.display_info.display_name
                except (AttributeError, OSError) as e:
                    # OSError -2147467263 = E_NOTIMPL (not implemented)
                    logger.debug(f"Could not get app_info: {e}")
                    pass

            # Skip our own notifications (prevent feedback loop)
            if app_id in ("Cortex", "Attention Firewall"):
                logger.debug(f"Skipping our own notification: {app_id}")
                return None

            # Get text content from toast binding
            title = ""
            body = ""

            try:
                # Get ToastGeneric binding template
                # pywinrt 2.0+ uses snake_case: toast_generic
                # Older versions might use ToastGeneric (PascalCase)
                if hasattr(KnownBindings, "toast_generic"):
                    toast_generic = KnownBindings.toast_generic
                elif hasattr(KnownBindings, "ToastGeneric"):
                    toast_generic = KnownBindings.ToastGeneric
                else:
                    attrs = [a for a in dir(KnownBindings) if not a.startswith("_")]
                    logger.warning(f"[EXTRACT] Cannot find toast_generic. Attrs: {attrs}")
                    toast_generic = None
                logger.debug(f"[EXTRACT] toast_generic={toast_generic}")

                # Try to get binding
                binding = None
                if hasattr(notif, "notification") and hasattr(notif.notification, "visual"):
                    visual = notif.notification.visual
                    logger.debug(f"[EXTRACT] visual={visual}, visual attrs={dir(visual)}")
                    if hasattr(visual, "GetBinding"):
                        binding = visual.GetBinding(toast_generic)
                    elif hasattr(visual, "get_binding"):
                        binding = visual.get_binding(toast_generic)
                    logger.debug(f"[EXTRACT] binding={binding}")
                else:
                    logger.debug(f"[EXTRACT] No visual property. notif attrs={dir(notif)}")

                if binding:
                    # Handle both API styles
                    if hasattr(binding, "GetTextElements"):
                        texts = list(binding.GetTextElements())
                    else:
                        texts = list(binding.get_text_elements())
                    logger.debug(f"[EXTRACT] texts={texts}, count={len(texts)}")
                    if texts:
                        # Text property might be Text or text
                        def get_text(t):
                            val = t.Text if hasattr(t, "Text") else t.text
                            logger.debug(f"[EXTRACT] text element: {val}")
                            return val

                        title = get_text(texts[0]) if texts else ""
                        body = " ".join(get_text(t) for t in texts[1:]) if len(texts) > 1 else ""
                else:
                    logger.debug("[EXTRACT] No binding found")
            except Exception as e:
                logger.warning(f"Could not extract text: {e}", exc_info=True)

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

        except OSError as e:
            # OSError -2147467263 = E_NOTIMPL (some notification properties not implemented)
            # This is normal for certain notification types - log at debug level
            logger.debug(f"Skipping notification with unimplemented properties: {e}")
            return None
        except Exception as e:
            logger.error(f"Error extracting notification data: {e}")
            return None

    def _extract_sender(self, app_id: str, title: str, body: str) -> str | None:
        """Try to extract sender name from notification content.

        Different apps format their notifications differently:
        - Teams: Title is often the sender name or channel
        - WhatsApp: Title is sender or group name
        - Phone Link: Title is sender name or phone number
        - Outlook: Title is sender name (unless generic "Outlook" title)
        """
        app_lower = app_id.lower()

        # Messaging apps where title = sender
        messaging_apps = ["teams", "whatsapp", "slack", "discord", "telegram", "phone link"]
        if any(app in app_lower for app in messaging_apps):
            # Title is the sender name or phone number
            return title if title else None

        # Outlook/Mail apps - more complex extraction
        if "outlook" in app_lower or "mail" in app_lower:
            return self._extract_outlook_sender(title, body)

        return None

    def _extract_outlook_sender(self, title: str, body: str) -> str | None:
        """Extract sender from Outlook notifications.

        Outlook notification patterns:
        - title='Microsoft account team', body='...' → sender is title
        - title='Outlook', body='Reaction Daily Digest...' → sender in body
        - title='Microsoft Outlook', body='...' → sender in body
        """
        # If title is NOT the generic app name, it's likely the sender
        generic_titles = ["outlook", "microsoft outlook", "mail", "microsoft mail"]
        if title and title.lower() not in generic_titles:
            return title

        # Title is generic - try to extract sender from body
        if body:
            # Pattern: "From: Sender Name" or "From: email@domain.com"
            # Match "From: X" pattern
            from_match = re.search(r"[Ff]rom[:\s]+([^<\n]+?)(?:\s*<|$|\n)", body)
            if from_match:
                sender = from_match.group(1).strip()
                if sender:
                    return sender

            # Pattern: "X reacted to" (reaction notifications)
            reacted_match = re.search(r"^([^:]+?)\s+reacted\s+to", body)
            if reacted_match:
                return reacted_match.group(1).strip()

            # Pattern: "X sent you" or "X shared"
            action_match = re.search(r"^([^:]+?)\s+(?:sent|shared|replied|commented)", body)
            if action_match:
                sender = action_match.group(1).strip()
                # Avoid matching entire sentences
                if len(sender.split()) <= 4:
                    return sender

        return None

    def _on_notification_changed(self, sender, args):
        """Callback when a notification is added or removed."""
        if not self._running:
            return

        try:
            # Only process additions
            if hasattr(args, "change_kind"):
                # We only care about new notifications, not removals
                pass

            # Get the notification - handle both API styles
            notif_id = (
                args.UserNotificationId
                if hasattr(args, "UserNotificationId")
                else args.user_notification_id
            )
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
            asyncio.run_coroutine_threadsafe(self.queue.put(data), self.loop)

        except Exception as e:
            logger.error(f"Error processing notification: {e}")

    async def start(self) -> None:
        """Start listening for notifications via polling.

        Note: Event-based listening (add_notification_changed) only works for UWP apps.
        For regular Python apps, we use polling instead.
        """
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

        self._running = True
        self._seen_ids: set[str] = set()

        # Start polling task
        self._poll_task = asyncio.create_task(self._poll_notifications())
        logger.info("Windows notification listener started (polling mode)")

    async def _poll_notifications(self, interval: float = 1.0) -> None:
        """Poll for new notifications periodically."""
        from winrt.windows.ui.notifications import NotificationKinds

        while self._running:
            try:
                # Get current notifications
                toast_kind = NotificationKinds.TOAST
                notifications = await self._listener.get_notifications_async(toast_kind)

                for notif in notifications:
                    notif_id = str(notif.id) if hasattr(notif, "id") else str(id(notif))

                    # Only process new notifications
                    if notif_id not in self._seen_ids:
                        self._seen_ids.add(notif_id)
                        data = self._extract_notification_data(notif)
                        if data:
                            logger.debug(f"New notification: {data.app_id} - {data.title}")
                            await self.queue.put(data)

                # Prune seen_ids to prevent memory growth (keep last 1000)
                if len(self._seen_ids) > 1000:
                    # Keep only IDs still in notification center
                    current_ids = {
                        str(n.id) if hasattr(n, "id") else str(id(n)) for n in notifications
                    }
                    self._seen_ids = self._seen_ids & current_ids

            except Exception as e:
                logger.error(f"Error polling notifications: {e}")

            await asyncio.sleep(interval)

    async def stop(self) -> None:
        """Stop listening for notifications."""
        self._running = False
        if hasattr(self, "_poll_task") and self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("Windows notification listener stopped")

    async def get_current_notifications(self) -> list[NotificationData]:
        """Get all current notifications in the notification center."""
        if not self._winrt or not self._listener:
            return []

        try:
            from winrt.windows.ui.notifications import NotificationKinds

            # Handle both API styles
            toast_kind = (
                NotificationKinds.Toast
                if hasattr(NotificationKinds, "Toast")
                else NotificationKinds.TOAST
            )
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
