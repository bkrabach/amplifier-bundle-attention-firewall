"""CLI entry point for Attention Firewall."""

import asyncio
import logging
import sys
from pathlib import Path

import click

from attention_firewall import __version__


def setup_logging(verbose: bool = False, log_file: Path | None = None) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    
    # Quiet down noisy libraries
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


@click.group()
@click.version_option(version=__version__)
def cli():
    """Attention Firewall - AI-powered Windows notification controller."""
    pass


@cli.command()
@click.option(
    "--data-dir", "-d",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory for state and logs (default: ~/.attention-firewall)",
)
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to policy configuration YAML",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose logging",
)
def run(data_dir: Path | None, config: Path | None, verbose: bool):
    """Run the Attention Firewall daemon."""
    setup_logging(verbose=verbose)
    
    from attention_firewall.daemon import run_daemon
    
    click.echo("Starting Attention Firewall...")
    click.echo("Press Ctrl+C to stop")
    click.echo()
    
    try:
        asyncio.run(run_daemon(data_dir=data_dir, config_path=config))
    except KeyboardInterrupt:
        click.echo("\nShutdown complete")


@cli.command()
@click.option(
    "--data-dir", "-d",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory (default: ~/.attention-firewall)",
)
@click.option("--hours", "-h", default=24, help="Hours to look back (default: 24)")
def summary(data_dir: Path | None, hours: int):
    """Generate a notification summary."""
    from attention_firewall.state import NotificationStateManager
    
    data_dir = data_dir or Path.home() / ".attention-firewall"
    db_path = data_dir / "notifications.db"
    
    if not db_path.exists():
        click.echo("No notification database found. Run the daemon first.")
        sys.exit(1)
    
    state = NotificationStateManager(db_path)
    stats = state.get_statistics(hours=hours)
    
    click.echo(f"\n📊 Notification Summary (last {hours} hours)")
    click.echo("=" * 50)
    click.echo(f"Total received: {stats['total']}")
    click.echo(f"  ✅ Surfaced:   {stats['surfaced']}")
    click.echo(f"  🚫 Suppressed: {stats['suppressed']}")
    click.echo(f"  📋 In digest:  {stats['digest']}")
    
    if stats['by_app']:
        click.echo("\nBy App:")
        for app, count in sorted(stats['by_app'].items(), key=lambda x: -x[1]):
            click.echo(f"  {app}: {count}")
    
    if stats['top_senders']:
        click.echo("\nTop Senders:")
        for sender, count in list(stats['top_senders'].items())[:5]:
            click.echo(f"  {sender}: {count}")


@cli.command()
@click.option(
    "--data-dir", "-d",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory (default: ~/.attention-firewall)",
)
def policies(data_dir: Path | None):
    """Show current policies (VIPs, keywords, muted apps)."""
    from attention_firewall.state import NotificationStateManager
    
    data_dir = data_dir or Path.home() / ".attention-firewall"
    db_path = data_dir / "notifications.db"
    
    if not db_path.exists():
        click.echo("No notification database found. Run the daemon first.")
        sys.exit(1)
    
    state = NotificationStateManager(db_path)
    policies = state.get_all_policies()
    
    click.echo("\n🛡️ Current Policies")
    click.echo("=" * 50)
    
    click.echo("\n⭐ VIP Senders:")
    if policies['vips']:
        for vip in sorted(policies['vips']):
            click.echo(f"  - {vip}")
    else:
        click.echo("  (none)")
    
    click.echo("\n🔑 Priority Keywords:")
    if policies['keywords']:
        for kw in sorted(policies['keywords']):
            click.echo(f"  - {kw}")
    else:
        click.echo("  (none)")
    
    click.echo("\n🔇 Muted Apps:")
    if policies['muted_apps']:
        for app, until in policies['muted_apps'].items():
            click.echo(f"  - {app} (until {until})")
    else:
        click.echo("  (none)")


@cli.command()
@click.argument("sender")
@click.option(
    "--data-dir", "-d",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory (default: ~/.attention-firewall)",
)
def add_vip(sender: str, data_dir: Path | None):
    """Add a sender to the VIP list."""
    from attention_firewall.state import NotificationStateManager
    
    data_dir = data_dir or Path.home() / ".attention-firewall"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "notifications.db"
    
    state = NotificationStateManager(db_path)
    state.add_vip(sender)
    
    click.echo(f"✅ Added '{sender}' to VIP list")


@cli.command()
@click.argument("sender")
@click.option(
    "--data-dir", "-d",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory (default: ~/.attention-firewall)",
)
def remove_vip(sender: str, data_dir: Path | None):
    """Remove a sender from the VIP list."""
    from attention_firewall.state import NotificationStateManager
    
    data_dir = data_dir or Path.home() / ".attention-firewall"
    db_path = data_dir / "notifications.db"
    
    if not db_path.exists():
        click.echo("No notification database found.")
        sys.exit(1)
    
    state = NotificationStateManager(db_path)
    if state.remove_vip(sender):
        click.echo(f"✅ Removed '{sender}' from VIP list")
    else:
        click.echo(f"'{sender}' was not in VIP list")


@cli.command()
@click.option(
    "--app", "-a",
    default="Test App",
    help="App name for test notification",
)
@click.option(
    "--title", "-t",
    default="Test Notification",
    help="Notification title",
)
@click.option(
    "--body", "-b",
    default="This is a test notification from Attention Firewall",
    help="Notification body",
)
@click.option(
    "--sender", "-s",
    default=None,
    help="Sender name",
)
def test(app: str, title: str, body: str, sender: str | None):
    """Send a test notification to verify setup."""
    from attention_firewall.toast import ToastSender
    
    async def send_test():
        toast = ToastSender()
        success = await toast.send(
            title=f"{app} | {sender or title}",
            body=body,
            urgency="normal",
            rationale="Test notification",
        )
        return success
    
    success = asyncio.run(send_test())
    
    if success:
        click.echo("✅ Test notification sent!")
        if not ToastSender()._winrt:
            click.echo("   (Note: Running in mock mode - notification was logged only)")
    else:
        click.echo("❌ Failed to send test notification")


@cli.command()
@click.option(
    "--server", "-s",
    default="http://localhost:8420",
    help="Amplifier server URL",
)
@click.option(
    "--device-id",
    default=None,
    help="Device identifier (default: hostname)",
)
@click.option(
    "--device-name",
    default=None,
    help="Human-readable device name",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose logging",
)
def client(server: str, device_id: str | None, device_name: str | None, verbose: bool):
    """Run in client mode - connect to amplifier-app-server.
    
    Captures local notifications and forwards them to the server.
    Receives push notifications from the server and displays them locally.
    
    Example:
        attention-firewall client --server http://hub.local:8420
    """
    setup_logging(verbose=verbose)
    
    from attention_firewall.client import run_client
    
    click.echo("Starting Attention Firewall client...")
    click.echo(f"Connecting to: {server}")
    click.echo("Press Ctrl+C to stop")
    click.echo()
    
    try:
        asyncio.run(run_client(
            server_url=server,
            device_id=device_id,
            device_name=device_name,
        ))
    except KeyboardInterrupt:
        click.echo("\nShutdown complete")


@cli.command()
@click.option(
    "--server", "-s",
    default="http://localhost:8420",
    help="Amplifier server URL to check",
)
def server_status(server: str):
    """Check amplifier-app-server status."""
    import httpx
    
    try:
        response = httpx.get(f"{server}/health", timeout=5)
        data = response.json()
        
        click.echo(f"\n🖥️  Server Status: {server}")
        click.echo("=" * 50)
        click.echo(f"Status: {'✅ ' + data['status'] if data['status'] == 'healthy' else '❌ ' + data['status']}")
        click.echo(f"Active sessions: {data.get('sessions', 0)}")
        click.echo(f"Connected devices: {data.get('connected_devices', 0)}")
        
    except httpx.ConnectError:
        click.echo(f"❌ Cannot connect to server at {server}")
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)


@cli.command()
def debug_winrt():
    """Debug pywinrt API to find correct method names."""
    click.echo("\n🔧 pywinrt API Debug")
    click.echo("=" * 50)
    
    try:
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )
        click.echo("✅ UserNotificationListener imported successfully")
        click.echo(f"   Type: {type(UserNotificationListener)}")
        click.echo(f"   Repr: {repr(UserNotificationListener)}")
        
        # List all attributes
        click.echo("\nUserNotificationListener attributes:")
        for attr in sorted(dir(UserNotificationListener)):
            if not attr.startswith('_'):
                try:
                    val = getattr(UserNotificationListener, attr)
                    click.echo(f"  - {attr}: {type(val).__name__}")
                except Exception as e:
                    click.echo(f"  - {attr}: (error: {e})")
        
        # Try calling request_access_async as a static/class method
        click.echo("\n🔬 Attempting to call methods directly on class...")
        
        try:
            # Maybe it's like a static method?
            result = UserNotificationListener.request_access_async()
            click.echo(f"   request_access_async() returned: {result}")
        except Exception as e:
            click.echo(f"   request_access_async() error: {e}")
        
        try:
            # Check if there's a way to get access status
            result = UserNotificationListener.get_access_status()
            click.echo(f"   get_access_status() returned: {result}")
        except Exception as e:
            click.echo(f"   get_access_status() error: {e}")
                
    except ImportError as e:
        click.echo(f"❌ Import failed: {e}")
    
    try:
        from winrt.windows.ui.notifications import KnownNotificationBindings
        click.echo("\n✅ KnownNotificationBindings imported successfully")
        click.echo("\nKnownNotificationBindings attributes:")
        for attr in sorted(dir(KnownNotificationBindings)):
            if not attr.startswith('_'):
                click.echo(f"  - {attr}")
    except ImportError as e:
        click.echo(f"❌ KnownNotificationBindings import failed: {e}")


@cli.command()
def check():
    """Check if notification listening is available."""
    import platform
    
    click.echo("\n🔍 System Check")
    click.echo("=" * 50)
    
    # Platform check
    is_windows = platform.system() == "Windows"
    click.echo(f"Platform: {platform.system()} {'✅' if is_windows else '⚠️ (not Windows)'}")
    
    # Check pywinrt
    try:
        from winrt.windows.ui.notifications.management import UserNotificationListener
        click.echo("pywinrt: ✅ Available")
        winrt_available = True
    except ImportError:
        click.echo("pywinrt: ❌ Not installed")
        click.echo("  Install with: pip install winrt-Windows.UI.Notifications winrt-Windows.UI.Notifications.Management")
        winrt_available = False
    
    # Check if we can create listener
    if winrt_available:
        import asyncio
        from attention_firewall.listener import WindowsNotificationListener
        
        queue = asyncio.Queue()
        listener = WindowsNotificationListener(queue)
        click.echo(f"Notification listener: {'✅ Ready' if listener.is_available else '❌ Not available'}")
    
    # Check toast capability
    from attention_firewall.toast import ToastSender
    toast = ToastSender()
    click.echo(f"Toast notifications: {'✅ Ready' if toast.is_available else '⚠️ Mock mode (logged only)'}")
    
    click.echo()
    if is_windows and winrt_available:
        click.echo("✅ System is ready for Attention Firewall!")
    else:
        click.echo("⚠️ Some features may not work. See messages above.")


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
