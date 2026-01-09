"""Notification ingest tool for Amplifier.

Receives captured notifications and provides context for agent scoring.
"""

from typing import Any


class NotificationIngestTool:
    """Tool for ingesting notifications from Windows listener.
    
    When called, logs the notification to state and returns context
    that helps the agent make filtering decisions (VIP status, keywords, etc.)
    """
    
    def __init__(self, state_manager):
        """Initialize with shared state manager.
        
        Args:
            state_manager: NotificationStateManager instance
        """
        self.state = state_manager
    
    @property
    def name(self) -> str:
        return "ingest_notification"
    
    @property
    def description(self) -> str:
        return """Log an incoming notification and get context for filtering decision.

Call this when a new notification arrives to:
1. Store it in the notification database
2. Get VIP/keyword/mute context to help make filtering decisions

Returns notification ID and context (is_vip, matched_keywords, is_app_muted, etc.)"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "app_id": {
                    "type": "string",
                    "description": "Source application (e.g., 'Microsoft Teams', 'WhatsApp')"
                },
                "title": {
                    "type": "string",
                    "description": "Notification title"
                },
                "body": {
                    "type": "string",
                    "description": "Notification body text"
                },
                "timestamp": {
                    "type": "string",
                    "description": "ISO8601 timestamp"
                },
                "sender": {
                    "type": "string",
                    "description": "Sender name/identifier if available"
                },
                "conversation_hint": {
                    "type": "string",
                    "description": "Conversation/thread identifier if available"
                }
            },
            "required": ["app_id", "title", "body", "timestamp"]
        }
    
    async def execute(self, **kwargs) -> dict[str, Any]:
        """Ingest notification and return context for decision."""
        app_id = kwargs.get("app_id", "Unknown")
        title = kwargs.get("title", "")
        body = kwargs.get("body", "")
        timestamp = kwargs.get("timestamp", "")
        sender = kwargs.get("sender")
        conversation_hint = kwargs.get("conversation_hint")
        
        # Store the notification
        notification_id = self.state.store_notification(
            app_id=app_id,
            title=title,
            body=body,
            timestamp=timestamp,
            sender=sender,
            conversation_hint=conversation_hint,
        )
        
        # Gather context for decision-making
        full_text = f"{title} {body}"
        
        # Check VIP status
        is_vip = self.state.is_vip(sender)
        
        # Check for keyword matches
        matched_keywords = self.state.check_keywords(full_text)
        
        # Check if app is muted
        is_app_muted = self.state.is_app_muted(app_id)
        
        # Check for suppress patterns
        suppress_match = self.state.matches_suppress_pattern(full_text)
        
        # Get recent count from this sender
        recent_from_sender = self.state.recent_from_sender(sender, hours=1)
        
        return {
            "success": True,
            "notification_id": notification_id,
            "context": {
                "app_id": app_id,
                "sender": sender,
                "is_vip": is_vip,
                "matched_keywords": matched_keywords,
                "is_app_muted": is_app_muted,
                "matches_suppress_pattern": suppress_match,
                "recent_from_sender": recent_from_sender,
            },
            "recommendation": self._get_recommendation(
                is_vip=is_vip,
                matched_keywords=matched_keywords,
                is_app_muted=is_app_muted,
                suppress_match=suppress_match,
            ),
        }
    
    def _get_recommendation(
        self,
        is_vip: bool,
        matched_keywords: list[str],
        is_app_muted: bool,
        suppress_match: str | None,
    ) -> str:
        """Generate a recommendation based on context."""
        if is_app_muted:
            return "SUPPRESS - App is currently muted"
        
        if suppress_match:
            return f"SUPPRESS - Matches noise pattern: '{suppress_match}'"
        
        if is_vip:
            return "SURFACE - VIP sender"
        
        if matched_keywords:
            keywords_str = ", ".join(matched_keywords[:3])
            return f"SURFACE - Contains priority keywords: {keywords_str}"
        
        return "EVALUATE - No automatic rules matched, use judgment"
