# -*- coding: utf-8 -*-
"""
This module defines base classes for desktop notifications. All platform implementations
must inherit from :class:`DesktopNotifierBase`.
"""

from __future__ import annotations

# system imports
import logging
import warnings
from enum import Enum, auto
from collections import deque
from pathlib import Path
from typing import (
    Dict,
    Callable,
    Any,
    Deque,
    List,
    Sequence,
    ContextManager,
)

try:
    from importlib.resources import as_file, files

    def resource_path(package: str, resource: str) -> ContextManager[Path]:
        return as_file(files(package) / resource)

except ImportError:
    from importlib.resources import path as resource_path


logger = logging.getLogger(__name__)

DEFAULT_SOUND = "default"
PYTHON_ICON_PATH = resource_path("desktop_notifier.resources", "python.png").__enter__()


class AuthorisationError(Exception):
    """Raised when we are not authorised to send notifications"""


class Urgency(Enum):
    """Enumeration of notification levels

    The interpretation and visuals will depend on the platform.
    """

    Critical = "critical"
    """For critical errors."""

    Normal = "normal"
    """Default platform notification level."""

    Low = "low"
    """Low priority notification."""


class Button:
    """
    A button for interactive notifications

    :param title: The button title.
    :param on_pressed: Callback to invoke when the button is pressed. This is called
        without any arguments.
    """

    def __init__(
        self,
        title: str,
        on_pressed: Callable[[], Any] | None = None,
    ) -> None:
        self.title = title
        self.on_pressed = on_pressed

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(title='{self.title}', on_pressed={self.on_pressed})>"


class ReplyField:
    """
    A reply field for interactive notifications

    :param title: A title for the field itself. On macOS, this will be the title of a
        button to show the field.
    :param button_title: The title of the button to send the reply.
    :param on_replied: Callback to invoke when the button is pressed. This is called
        without any arguments.
    """

    def __init__(
        self,
        title: str = "Reply",
        button_title: str = "Send",
        on_replied: Callable[[str], Any] | None = None,
    ) -> None:
        self.title = title
        self.button_title = button_title
        self.on_replied = on_replied

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(title='{self.title}', on_replied={self.on_replied})>"


class Notification:
    """A desktop notification

    :param title: Notification title.
    :param message: Notification message.
    :param urgency: Notification level: low, normal or critical.
    :param icon: URI for an icon to use for the notification or icon name.
    :param buttons: A list of buttons for the notification.
    :param reply_field: An optional reply field/
    :param on_clicked: Callback to call when the notification is clicked. The
        callback will be called without any arguments.
    :param on_dismissed: Callback to call when the notification is dismissed. The
        callback will be called without any arguments.
    :param attachment: URI for an attachment to the notification.
    :param sound: [DEPRECATED] Use sound_file=DEFAULT_SOUND instead.
    :param thread: An identifier to group related notifications together.
    :param timeout: Duration for which the notification in shown.
    :param sound_file: String identifying the sound to play when the notification is
        shown. Pass desktop_notifier.DEFAULT_SOUND to use the default sound.
    """

    def __init__(
        self,
        title: str,
        message: str,
        urgency: Urgency = Urgency.Normal,
        icon: str | None = None,
        buttons: Sequence[Button] = (),
        reply_field: ReplyField | None = None,
        on_clicked: Callable[[], Any] | None = None,
        on_dismissed: Callable[[], Any] | None = None,
        attachment: str | None = None,
        sound: bool = False,
        thread: str | None = None,
        timeout: int = -1,
        sound_file: str | None = None,
    ) -> None:
        if sound is True:
            warnings.warn(
                "Use sound_file=DEFAULT_SOUND instead of sound=True.",
                DeprecationWarning,
            )
            sound_file = DEFAULT_SOUND

        self._identifier = ""
        self._winrt_identifier = ""
        self._macos_identifier = ""
        self._dbus_identifier = 0

        self.title = title
        self.message = message
        self.urgency = urgency
        self.icon = icon
        self.buttons = buttons
        self.reply_field = reply_field
        self.on_clicked = on_clicked
        self.on_dismissed = on_dismissed
        self.attachment = attachment
        self.sound_file = sound_file
        self.thread = thread
        self.timeout = timeout

    @property
    def identifier(self) -> str:
        return self._identifier

    @identifier.setter
    def identifier(self, nid: str) -> None:
        self._identifier = nid

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(title='{self.title}', message='{self.message}')>"


class Capability(Enum):
    APP_NAME = auto()
    TITLE = auto()
    MESSAGE = auto()
    URGENCY = auto()
    ICON = auto()
    ICON_FILE = auto()
    ICON_NAME = auto()
    BUTTONS = auto()
    REPLY_FIELD = auto()
    ATTACHMENT = auto()
    ON_CLICKED = auto()
    ON_DISMISSED = auto()
    SOUND = auto()
    SOUND_FILE = auto()
    SOUND_NAME = auto()
    THREAD = auto()
    TIMEOUT = auto()


class DesktopNotifierBase:
    """Base class for desktop notifier implementations

    :param app_name: Name to identify the application in the notification center.
    :param notification_limit: Maximum number of notifications to keep in the system's
        notification center.
    """

    def __init__(
        self,
        app_name: str = "Python",
        notification_limit: int | None = None,
    ) -> None:
        self.app_name = app_name
        self.notification_limit = notification_limit
        self._current_notifications: Deque[Notification] = deque([], notification_limit)
        self._notification_for_nid: Dict[str, Notification] = {}

    async def request_authorisation(self) -> bool:
        """
        Request authorisation to send notifications.

        :returns: Whether authorisation has been granted.
        """
        raise NotImplementedError()

    async def has_authorisation(self) -> bool:
        """
        Returns whether we have authorisation to send notifications.
        """
        raise NotImplementedError()

    async def send(self, notification: Notification) -> None:
        """
        Sends a desktop notification. Some arguments may be ignored, depending on the
        implementation. This is a wrapper method which mostly performs housekeeping of
        notifications ID and calls :meth:`_send` to actually schedule the notification.
        Platform implementations must implement :meth:`_send`.

        :param notification: Notification to send.
        """
        notification_to_replace: Notification | None

        if len(self._current_notifications) == self.notification_limit:
            notification_to_replace = self._current_notifications.popleft()
        else:
            notification_to_replace = None

        try:
            await self._send(notification, notification_to_replace)
        except Exception:
            # Notifications can fail for many reasons:
            # The dbus service may not be available, we might be in a headless session,
            # etc. Since notifications are not critical to an application, we only emit
            # a warning.
            if notification_to_replace:
                self._current_notifications.appendleft(notification_to_replace)
            logger.warning("Notification failed", exc_info=True)
        else:
            self._current_notifications.append(notification)
            self._notification_for_nid[notification.identifier] = notification

    def _clear_notification_from_cache(self, notification: Notification) -> None:
        """
        Removes the notification from our cache. Should be called by backends when the
        notification is closed.
        """
        try:
            self._current_notifications.remove(notification)
        except ValueError:
            pass

        if notification.identifier:
            try:
                self._notification_for_nid.pop(notification.identifier)
            except KeyError:
                pass

    async def _send(
        self,
        notification: Notification,
        notification_to_replace: Notification | None,
    ) -> None:
        """
        Method to send a notification via the platform. This should be implemented by
        subclasses.

        Implementations must raise an exception when the notification could not be
        delivered. If the notification could be delivered but not fully as intended,
        e.g., because associated resources could not be loaded, implementations should
        emit a log message of level warning.

        :param notification: Notification to send.
        :param notification_to_replace: Notification to replace, if any.
        :returns: The platform's ID for the scheduled notification.
        """
        raise NotImplementedError()

    @property
    def current_notifications(self) -> List[Notification]:
        """
        A list of all notifications which currently displayed in the notification center
        """
        return list(self._current_notifications)

    async def clear(self, notification: Notification) -> None:
        """
        Removes the given notification from the notification center. This is a wrapper
        method which mostly performs housekeeping of notifications ID and calls
        :meth:`_clear` to actually clear the notification. Platform implementations
        must implement :meth:`_clear`.

        :param notification: Notification to clear.
        """

        if notification.identifier:
            await self._clear(notification)

        self._clear_notification_from_cache(notification)

    async def _clear(self, notification: Notification) -> None:
        """
        Removes the given notification from the notification center. Should be
        implemented by subclasses.

        :param notification: Notification to clear.
        """
        raise NotImplementedError()

    async def clear_all(self) -> None:
        """
        Clears all notifications from the notification center. This is a wrapper method
        which mostly performs housekeeping of notifications ID and calls
        :meth:`_clear_all` to actually clear the notifications. Platform implementations
        must implement :meth:`_clear_all`.
        """

        await self._clear_all()
        self._current_notifications.clear()
        self._notification_for_nid.clear()

    async def _clear_all(self) -> None:
        """
        Clears all notifications from the notification center. Should be implemented by
        subclasses.
        """
        raise NotImplementedError()

    async def get_capabilities(self) -> frozenset[Capability]:
        """
        Returns the functionality supported by the implementation and, for Linux / dbus,
        the notification server.
        """
        raise NotImplementedError()
