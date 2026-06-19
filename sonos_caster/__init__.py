"""Sonos Caster — forward Windows system audio to a Sonos speaker over UPnP.

Captures the PC's output via WASAPI loopback, serves it as an HTTP audio
stream on the LAN, and asks Sonos (via SoCo) to play that URL. Low-latency,
no AirPlay encryption to deal with.
"""

__version__ = "0.1.0"
