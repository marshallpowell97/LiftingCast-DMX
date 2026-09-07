#!/usr/bin/env python3
"""
OK-026-24-WLA Wall Washer Light Controller
Handles DMX control for the 24PCS LED washer wall light
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
import logging
from dmx_controller import EnttecOpenDMX

logger = logging.getLogger(__name__)


class WasherMode(Enum):
    """Washer DMX Mode enumeration"""
    CH_6 = (6, "6 Channel RGBA")
    CH_9 = (9, "9 Channel with Master Dimmer")
    CH_16 = (16, "16 Channel")
    CH_30 = (30, "30 Channel")
    CH_58 = (58, "58 Channel")

    def __init__(self, channels: int, description: str):
        self.channels = channels
        self.description = description


@dataclass
class ColorRGBA:
    """RGBA color representation"""
    r: int = 0  # 0-255
    g: int = 0  # 0-255
    b: int = 0  # 0-255
    a: int = 0  # 0-255 (Amber)


class WasherLightController:
    """
    Controller for OK-026-24-WLA 24PCS LED Washer Wall Light
    Handles 9-channel mode with master dimmer for full control
    """

    def __init__(self, dmx_controller: EnttecOpenDMX, start_channel: int = 1):
        """
        Initialize washer light controller

        Args:
            dmx_controller: DMX interface controller
            start_channel: Starting DMX channel (1-512)
        """
        self.dmx = dmx_controller
        self.start_channel = start_channel
        self.current_mode = WasherMode.CH_9  # Using 9-channel mode with master dimmer

        # Current color state
        self.rgba_color = ColorRGBA(255, 255, 255, 0)
        self.master_dimmer = 255  # 0-255 master dimmer
        self.strobe = 0  # 0-9 = no strobe, 10-255 = strobe speed
        self.auto_program = 0  # 0-255 (0 = off)
        self.color_chase = 0  # 0-255 (see manual for chase table)
        self.chase_speed = 0  # 0-255 (slow to fast)

    def set_mode(self, mode: WasherMode):
        """Change the DMX mode"""
        self.current_mode = mode
        logger.info(f"Changed to mode: {mode.description} ({mode.channels} channels)")
        self._update_light()

    def set_rgb_color(self, r: int, g: int, b: int, intensity: Optional[float] = None):
        """
        Set RGB color (amber set to 0)

        Args:
            r, g, b: RGB values (0-255)
            intensity: Intensity percentage (0-100) - sets master dimmer
        """
        # Set RGB at full values
        self.rgba_color = ColorRGBA(
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)),
            0  # No amber
        )

        # Use intensity for master dimmer instead of scaling RGB
        if intensity is not None:
            self.master_dimmer = int((intensity / 100.0) * 255)
        else:
            self.master_dimmer = 255

        # Disable effects when setting manual color
        self.strobe = 0
        self.auto_program = 0
        self.color_chase = 0
        self.chase_speed = 0

        self._update_light()

    def set_rgba_color(self, r: int, g: int, b: int, a: int, intensity: Optional[float] = None):
        """
        Set RGBA color including amber

        Args:
            r, g, b, a: RGBA values (0-255)
            intensity: Intensity percentage (0-100) - sets master dimmer
        """
        self.rgba_color = ColorRGBA(
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)),
            max(0, min(255, a))
        )

        # Use intensity for master dimmer
        if intensity is not None:
            self.master_dimmer = int((intensity / 100.0) * 255)
        else:
            self.master_dimmer = 255

        # Disable effects when setting manual color
        self.strobe = 0
        self.auto_program = 0
        self.color_chase = 0
        self.chase_speed = 0

        self._update_light()

    def set_chase_effect(self, chase_effect: int, speed: int = 128):
        """
        Set color chase effect

        Args:
            chase_effect: Chase effect number (see manual color chase table)
            speed: Chase speed 0-255 (slow to fast)
        """
        self.color_chase = max(0, min(255, chase_effect))
        self.chase_speed = max(0, min(255, speed))
        self._update_light()

    def off(self):
        """Turn off the light"""
        self.master_dimmer = 0
        self.rgba_color = ColorRGBA(0, 0, 0, 0)
        self.strobe = 0
        self.auto_program = 0
        self.color_chase = 0
        self.chase_speed = 0
        self._update_light()

    def _update_light(self):
        """Update the DMX channels based on current state"""
        if not self.dmx.is_connected:
            logger.warning("DMX controller not connected")
            return

        # 9-channel mode mapping
        channels = {
            self.start_channel:     self.master_dimmer,  # CH1: Master Dimmer
            self.start_channel + 1: self.strobe,         # CH2: Strobe
            self.start_channel + 2: self.rgba_color.r,   # CH3: Red
            self.start_channel + 3: self.rgba_color.g,   # CH4: Green
            self.start_channel + 4: self.rgba_color.b,   # CH5: Blue
            self.start_channel + 5: self.rgba_color.a,   # CH6: Amber
            self.start_channel + 6: self.auto_program,   # CH7: Auto program
            self.start_channel + 7: self.color_chase,    # CH8: Color Chase
            self.start_channel + 8: self.chase_speed     # CH9: Chase Speed
        }

        self.dmx.set_channels(channels)

        # Log the channel values for debugging - use INFO not DEBUG so we can see it
        logger.info(f"Washer @ Ch{self.start_channel}: Dimmer={self.master_dimmer} "
                   f"Strobe={self.strobe} R={self.rgba_color.r} G={self.rgba_color.g} "
                   f"B={self.rgba_color.b} A={self.rgba_color.a}")


if __name__ == "__main__":
    print("OK-026-24-WLA Washer Light Controller initialized")
