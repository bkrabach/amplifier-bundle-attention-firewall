"""Toast notification tool for Amplifier.

Surfaces important notifications to the user via Windows toasts.
"""

from typing import Any

from attention_firewall.toast import ToastSender


class SendToastTool:
    """Tool for raising agent-filtered notifications.
    
    Use this when a notification passes filtering criteria and
    should be surfaced to the user.
    """
    
    def __init__(self, toast_sender: ToastSender | None = None):
        """Initialize with toast sender.
        
        Args:
            toast_sender: ToastSender instance (creates one if not provided)
        """
        self.toast_sender = toast_sender or ToastSender()
    
    @property
    def name(self) -> str:
        return "send_toast"
    
    @property
    def description(self) -> str:
        return """Surface an important notification to the user.

Use this when a notification passes your filtering criteria and deserves 
the user's attention. Include a brief rationale explaining why you're 
surfacing this notification.

Urgency levels:
- "low": Silent notification, just appears in action center
- "normal": Standard notification with sound
- "high": Urgent notification that stays visible longer"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Notification title - include source app and sender (e.g., 'Teams | Alice Chen')"
                },
                "body": {
                    "type": "string",
                    "description": "Notification body - key content, can be truncated"
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Urgency level affecting how the notification is displayed"
                },
                "rationale": {
                    "type": "string",
                    "description": "Brief explanation of why this notification is being surfaced (e.g., 'VIP sender', 'deadline mentioned')"
                },
                "app_source": {
                    "type": "string",
                    "description": "Original app that generated this notification"
                }
            },
            "required": ["title", "body"]
        }
    
    async def execute(self, **kwargs) -> dict[str, Any]:
        """Send a toast notification."""
        title = kwargs.get("title", "Notification")
        body = kwargs.get("body", "")
        urgency = kwargs.get("urgency", "normal")
        rationale = kwargs.get("rationale")
        app_source = kwargs.get("app_source")
        
        # Validate urgency
        if urgency not in ("low", "normal", "high"):
            urgency = "normal"
        
        # Send the toast
        success = await self.toast_sender.send(
            title=title,
            body=body,
            urgency=urgency,
            rationale=rationale,
            app_source=app_source,
        )
        
        return {
            "success": success,
            "message": "Toast notification sent" if success else "Failed to send toast",
            "title": title,
            "urgency": urgency,
        }
