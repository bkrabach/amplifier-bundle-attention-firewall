"""Main daemon service for Attention Firewall.

Runs the notification listener, Amplifier session, and scheduler together.
"""

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

import yaml

from attention_firewall.listener import NotificationData, create_listener
from attention_firewall.scheduler import DigestScheduler
from attention_firewall.state import NotificationStateManager
from attention_firewall.toast import ToastSender
from attention_firewall.tools.ingest import NotificationIngestTool
from attention_firewall.tools.notify import SendToastTool
from attention_firewall.tools.policy import PolicyTool
from attention_firewall.tools.summary import SummaryTool

logger = logging.getLogger(__name__)

# Default data directory
DEFAULT_DATA_DIR = Path.home() / ".attention-firewall"


class AttentionFirewallDaemon:
    """Main daemon that orchestrates the Attention Firewall service.
    
    Components:
    - NotificationListener: Captures Windows notifications
    - NotificationStateManager: Persists notifications and policies
    - DigestScheduler: Schedules periodic summaries
    - Amplifier Session: AI agent for filtering decisions
    """
    
    def __init__(
        self,
        data_dir: Path | str | None = None,
        config_path: Path | str | None = None,
    ):
        """Initialize the daemon.
        
        Args:
            data_dir: Directory for state database and logs
            config_path: Path to policy configuration YAML
        """
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.config_path = Path(config_path) if config_path else None
        self.config: dict[str, Any] = {}
        
        # Event queue for notifications
        self.notification_queue: asyncio.Queue[NotificationData] = asyncio.Queue()
        
        # Components (initialized in start())
        self.state: NotificationStateManager | None = None
        self.listener = None
        self.scheduler: DigestScheduler | None = None
        self.toast_sender: ToastSender | None = None
        
        # Tools
        self.tools: dict[str, Any] = {}
        
        # Control flags
        self._running = False
        self._shutdown_event = asyncio.Event()
    
    def _load_config(self) -> dict[str, Any]:
        """Load configuration from YAML file."""
        # Try paths in order
        paths_to_try = [
            self.config_path,
            self.data_dir / "config.yaml",
            Path(__file__).parent.parent.parent / "config" / "default-policy.yaml",
        ]
        
        for path in paths_to_try:
            if path and path.exists():
                logger.info(f"Loading config from {path}")
                with open(path) as f:
                    return yaml.safe_load(f) or {}
        
        logger.warning("No config file found, using defaults")
        return {}
    
    def _init_components(self, loop: asyncio.AbstractEventLoop) -> None:
        """Initialize all components."""
        # Load configuration
        self.config = self._load_config()
        global_config = self.config.get("global", {})
        
        # State manager
        db_path = self.data_dir / "notifications.db"
        self.state = NotificationStateManager(db_path)
        
        # Load default policies from config
        self._apply_config_policies()
        
        # Toast sender
        self.toast_sender = ToastSender()
        
        # Create tools
        self.tools = {
            "ingest_notification": NotificationIngestTool(self.state),
            "send_toast": SendToastTool(self.toast_sender),
            "manage_policy": PolicyTool(self.state),
            "generate_summary": SummaryTool(self.state),
        }
        
        # Notification listener
        self.listener = create_listener(self.notification_queue, loop)
        
        # Scheduler
        self.scheduler = DigestScheduler()
        self.scheduler.register_callback("generate_digest", self._on_scheduled_digest)
        self.scheduler.setup_from_config(global_config)
    
    def _apply_config_policies(self) -> None:
        """Apply policies from config file to state manager."""
        global_config = self.config.get("global", {})
        
        # Add VIP senders
        for sender in global_config.get("vip_senders", []):
            self.state.add_vip(sender)
        
        # Add priority keywords
        for keyword in global_config.get("priority_keywords", []):
            self.state.add_keyword(keyword)
        
        # Add suppress patterns
        for pattern in global_config.get("suppress_patterns", []):
            self.state.add_suppress_pattern(pattern)
        
        logger.info(
            f"Loaded policies: {len(self.state.get_vips())} VIPs, "
            f"{len(self.state.get_keywords())} keywords"
        )
    
    async def _on_scheduled_digest(
        self, 
        digest_type: str = "scheduled", 
        job_id: str = ""
    ) -> None:
        """Handle scheduled digest generation."""
        logger.info(f"Generating {digest_type} digest")
        
        # Use summary tool to generate digest
        summary_tool = self.tools.get("generate_summary")
        if summary_tool:
            result = await summary_tool.execute(
                timeframe=24 if digest_type == "daily" else 1,
                clear_pending=True,
            )
            
            # Send toast with summary
            if self.toast_sender and result.get("total_pending", 0) > 0:
                await self.toast_sender.send_summary(
                    title=f"{digest_type.title()} Digest",
                    items=result.get("notifications", []),
                    timeframe=f"last {'24 hours' if digest_type == 'daily' else 'hour'}",
                )
    
    async def _process_notification(self, notif: NotificationData) -> None:
        """Process a single notification through the filtering pipeline.
        
        This is where the AI agent would normally make decisions.
        For now, we use rule-based filtering with the tools.
        """
        # Step 1: Ingest and get context
        ingest_tool = self.tools.get("ingest_notification")
        context_result = await ingest_tool.execute(
            app_id=notif.app_id,
            title=notif.title,
            body=notif.body,
            timestamp=notif.timestamp,
            sender=notif.sender,
            conversation_hint=notif.conversation_hint,
        )
        
        notification_id = context_result.get("notification_id")
        context = context_result.get("context", {})
        recommendation = context_result.get("recommendation", "")
        
        logger.debug(
            f"Notification from {notif.app_id}: {notif.title[:50]} "
            f"- Recommendation: {recommendation}"
        )
        
        # Step 2: Make decision based on context
        decision = "digest"
        rationale = None
        should_surface = False
        
        if context.get("is_app_muted"):
            decision = "suppressed"
            rationale = "App is muted"
        elif context.get("matches_suppress_pattern"):
            decision = "suppressed"
            rationale = f"Matches noise pattern: {context['matches_suppress_pattern']}"
        elif context.get("is_vip"):
            decision = "surfaced"
            rationale = "VIP sender"
            should_surface = True
        elif context.get("matched_keywords"):
            decision = "surfaced"
            keywords = context["matched_keywords"][:3]
            rationale = f"Keywords: {', '.join(keywords)}"
            should_surface = True
        else:
            decision = "digest"
            rationale = "Added to digest queue"
        
        # Step 3: Update notification with decision
        self.state.update_notification_decision(
            notification_id,
            decision=decision,
            rationale=rationale,
            surfaced=should_surface,
        )
        
        # Step 4: Surface if needed
        if should_surface:
            toast_tool = self.tools.get("send_toast")
            await toast_tool.execute(
                title=f"{notif.app_id} | {notif.sender or notif.title}",
                body=notif.body[:200] if notif.body else notif.title,
                urgency="normal" if decision == "surfaced" else "high",
                rationale=rationale,
                app_source=notif.app_id,
            )
        
        logger.info(f"[{decision.upper()}] {notif.app_id}: {notif.title[:40]}... ({rationale})")
    
    async def _notification_processor(self) -> None:
        """Background task that processes notifications from the queue."""
        logger.info("Notification processor started")
        
        while self._running:
            try:
                # Wait for notification with timeout (allows checking shutdown)
                try:
                    notif = await asyncio.wait_for(
                        self.notification_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process the notification
                await self._process_notification(notif)
                
            except Exception as e:
                logger.error(f"Error processing notification: {e}", exc_info=True)
        
        logger.info("Notification processor stopped")
    
    async def start(self) -> None:
        """Start the daemon service."""
        if self._running:
            logger.warning("Daemon already running")
            return
        
        logger.info("Starting Attention Firewall daemon...")
        
        # Get the event loop
        loop = asyncio.get_event_loop()
        
        # Initialize components
        self._init_components(loop)
        
        # Request notification access
        if not await self.listener.request_access():
            raise PermissionError("Notification access not granted")
        
        self._running = True
        self._shutdown_event.clear()
        
        # Start components
        await self.listener.start()
        self.scheduler.start()
        
        # Start notification processor
        processor_task = asyncio.create_task(self._notification_processor())
        
        logger.info("Attention Firewall daemon started")
        logger.info(f"Data directory: {self.data_dir}")
        logger.info(f"Listener available: {self.listener.is_available}")
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        # Cleanup
        logger.info("Shutting down...")
        self._running = False
        
        await self.listener.stop()
        self.scheduler.stop()
        
        # Wait for processor to finish
        processor_task.cancel()
        try:
            await processor_task
        except asyncio.CancelledError:
            pass
        
        logger.info("Attention Firewall daemon stopped")
    
    def stop(self) -> None:
        """Signal the daemon to stop."""
        self._shutdown_event.set()
    
    async def inject_test_notification(
        self,
        app_id: str = "Test App",
        title: str = "Test Notification",
        body: str = "This is a test notification",
        sender: str | None = None,
    ) -> None:
        """Inject a test notification for development/testing."""
        if hasattr(self.listener, "inject_test_notification"):
            await self.listener.inject_test_notification(
                app_id=app_id,
                title=title,
                body=body,
                sender=sender,
            )
        else:
            # Manual injection for Windows listener
            from datetime import datetime
            notif = NotificationData(
                notification_id="test-" + str(id(self)),
                app_id=app_id,
                title=title,
                body=body,
                timestamp=datetime.now().isoformat(),
                sender=sender,
            )
            await self.notification_queue.put(notif)


def setup_signal_handlers(daemon: AttentionFirewallDaemon) -> None:
    """Set up signal handlers for graceful shutdown."""
    def handle_signal(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        daemon.stop()
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)


async def run_daemon(
    data_dir: Path | str | None = None,
    config_path: Path | str | None = None,
) -> None:
    """Run the daemon service."""
    daemon = AttentionFirewallDaemon(
        data_dir=data_dir,
        config_path=config_path,
    )
    
    setup_signal_handlers(daemon)
    
    await daemon.start()
