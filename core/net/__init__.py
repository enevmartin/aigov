"""Outbound HTTP: the polite client every collector must use (чл. 5)."""

from core.net.polite import USER_AGENT, PoliteClient, RobotsDenied

__all__ = ["USER_AGENT", "PoliteClient", "RobotsDenied"]
