"""Client mode for Attention Firewall.

Connects to an amplifier-app-server instance and:
- Forwards captured notifications to the server
- Receives push notifications from the server
- Displays server notifications as Windows toasts
"""

import asyncio
import json
import logging
import platform
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from attention_firewall.listener import NotificationData, create_listener
from attention_firewall.toast import ToastSender

logger = logging.getLogger(__name__)


class AttentionFirewallClient:
    """Client that connects to amplifier-app-server.
    
    Captures local notifications and forwards them to the server,
    receives push notifications and displays them locally.
    """
    
    def __init__(
        self,
        server_url: str = "http://localhost:8420",
        device_id: str | None = None,
        device_name: str | None = None,
    ):
        """Initialize the client.
        
        Args:
            server_url: URL of the amplifier-app-server
            device_id: Unique device identifier (default: hostname)
            device_name: Human-readable device name
        """
        self.server_url = server_url.rstrip("/")
        self.ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        
        self.device_id = device_id or socket.gethostname()
        self.device_name = device_name or f"{socket.gethostname()} ({platform.system()})"
        
        # Components
        self.notification_queue: asyncio.Queue[NotificationData] = asyncio.Queue()
        self.listener = None
        self.toast_sender = ToastSender()
        self.http_client: httpx.AsyncClient | None = None
        
        # WebSocket connection
        self._ws = None
        self._ws_task: asyncio.Task | None = None
        
        # Control
        self._running = False
        self._shutdown_event = asyncio.Event()
    
    async def _connect_websocket(self) -> None:
        """Connect to server WebSocket for push notifications."""
        try:
            import websockets
        except ImportError:
            logger.warning("websockets not installed - push notifications disabled")
            logger.warning("Install with: pip install websockets")
            return
        
        from urllib.parse import quote
        ws_endpoint = f"{self.ws_url}/ws/device/{self.device_id}?platform=windows&device_name={quote(self.device_name)}"
        
        while self._running:
            try:
                logger.info(f"Connecting to server WebSocket: {ws_endpoint}")
                
                async with websockets.connect(ws_endpoint) as ws:
                    self._ws = ws
                    logger.info("WebSocket connected - listening for push notifications")
                    
                    # Listen for messages
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            await self._handle_server_message(data)
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON from server: {message[:100]}")
                        except Exception as e:
                            logger.error(f"Error handling server message: {e}")
                            
            except Exception as e:
                logger.warning(f"WebSocket connection lost: {e}")
                self._ws = None
                
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def _handle_server_message(self, data: dict[str, Any]) -> None:
        """Handle a message from the server."""
        msg_type = data.get("type", "")
        payload = data.get("payload", {})
        
        if msg_type == "notification":
            # Display push notification as Windows toast
            await self.toast_sender.send(
                title=payload.get("title", "Notification"),
                body=payload.get("body", ""),
                urgency=payload.get("urgency", "normal"),
                rationale=payload.get("rationale"),
                app_source=payload.get("app_source"),
            )
            logger.info(f"Displayed push notification: {payload.get('title', '')[:50]}")
            
        elif msg_type == "pong":
            pass  # Heartbeat response
            
        else:
            logger.debug(f"Unknown message type: {msg_type}")
    
    async def _forward_notification(self, notif: NotificationData) -> bool:
        """Forward a notification to the server.
        
        Returns:
            True if successfully sent
        """
        if not self.http_client:
            return False
        
        try:
            payload = {
                "device_id": self.device_id,
                "app_id": notif.app_id,
                "title": notif.title,
                "body": notif.body,
                "timestamp": notif.timestamp,
                "sender": notif.sender,
                "conversation_hint": notif.conversation_hint,
                "metadata": {},
            }
            
            response = await self.http_client.post(
                f"{self.server_url}/notifications/ingest",
                json=payload,
                timeout=10,
            )
            
            if response.status_code == 200:
                logger.debug(f"Forwarded notification from {notif.app_id}")
                return True
            else:
                logger.warning(f"Server rejected notification: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to forward notification: {e}")
            return False
    
    async def _notification_forwarder(self) -> None:
        """Background task that forwards notifications to the server."""
        logger.info("Notification forwarder started")
        
        while self._running:
            try:
                # Wait for notification with timeout
                try:
                    notif = await asyncio.wait_for(
                        self.notification_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Forward to server
                await self._forward_notification(notif)
                
            except Exception as e:
                logger.error(f"Forwarder error: {e}", exc_info=True)
        
        logger.info("Notification forwarder stopped")
    
    async def check_server(self) -> dict[str, Any]:
        """Check server connectivity and status.
        
        Returns:
            Server status dict or error info
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.server_url}/health", timeout=5)
                return response.json()
        except httpx.ConnectError:
            return {"status": "unreachable", "error": f"Cannot connect to {self.server_url}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def start(self) -> None:
        """Start the client."""
        if self._running:
            logger.warning("Client already running")
            return
        
        logger.info(f"Starting Attention Firewall client...")
        logger.info(f"Server: {self.server_url}")
        logger.info(f"Device ID: {self.device_id}")
        
        # Check server connectivity
        status = await self.check_server()
        if status.get("status") != "healthy":
            logger.warning(f"Server not healthy: {status}")
            logger.warning("Continuing anyway - will retry connections")
        else:
            logger.info(f"Server online - {status.get('sessions', 0)} sessions, {status.get('connected_devices', 0)} devices")
        
        # Get event loop
        loop = asyncio.get_event_loop()
        
        # Initialize components
        self.listener = create_listener(self.notification_queue, loop)
        self.http_client = httpx.AsyncClient()
        
        # Request notification access
        if not await self.listener.request_access():
            logger.warning("Notification access not granted - running in limited mode")
        
        self._running = True
        self._shutdown_event.clear()
        
        # Start components
        await self.listener.start()
        
        # Start background tasks
        forwarder_task = asyncio.create_task(self._notification_forwarder())
        ws_task = asyncio.create_task(self._connect_websocket())
        self._ws_task = ws_task
        
        logger.info("Attention Firewall client started")
        logger.info(f"Listener available: {self.listener.is_available}")
        
        # Wait for shutdown
        await self._shutdown_event.wait()
        
        # Cleanup
        logger.info("Shutting down client...")
        self._running = False
        
        await self.listener.stop()
        
        if self.http_client:
            await self.http_client.aclose()
        
        # Cancel tasks
        forwarder_task.cancel()
        ws_task.cancel()
        
        try:
            await forwarder_task
        except asyncio.CancelledError:
            pass
        
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        
        logger.info("Attention Firewall client stopped")
    
    def stop(self) -> None:
        """Signal the client to stop."""
        self._shutdown_event.set()


async def run_client(
    server_url: str = "http://localhost:8420",
    device_id: str | None = None,
    device_name: str | None = None,
) -> None:
    """Run the client service."""
    import signal
    
    client = AttentionFirewallClient(
        server_url=server_url,
        device_id=device_id,
        device_name=device_name,
    )
    
    # Set up signal handlers
    def handle_signal(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        client.stop()
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    await client.start()
