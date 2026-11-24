"""The one place a provider is built from the configuration."""

from __future__ import annotations

from agent_build_kit.config import NotificationProvider, NotificationsConfig
from agent_build_kit.notify.command import CommandNotifier
from agent_build_kit.notify.provider import Notifier
from agent_build_kit.notify.windows import WindowsNotifier


def build_notifier(config: NotificationsConfig) -> Notifier | None:
    """The provider `config` names, or None when notifications are off."""
    match config.provider:
        case NotificationProvider.OFF:
            return None
        case NotificationProvider.COMMAND:
            return CommandNotifier(config.command)
        case NotificationProvider.WINDOWS:
            return WindowsNotifier()
