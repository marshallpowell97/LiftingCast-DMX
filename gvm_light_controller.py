#!/usr/bin/env python3
"""
GVM GVM-PRO-BD45R Light Controller
Handles all DMX modes and channel mappings for the GVM light
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Union
import logging
import colorsys
from dmx_controller import EnttecOpenDMX, LightingSignalHandler

logger = logging.getLogger(__name__)


class GVMMode(Enum):
    """GVM DMX Mode enumeration based on documentation"""
    CCT_RGB_33 = ("CCT&RGB 8-bit PIXEL=33", 7)
    CCT_HSI_33 = ("CCT&HSI 8-bit PIXEL=33", 6)
    CCT_33 = ("CCT 8-bit PIXEL=33", 3)
    RGB_33 = ("RGB 8-bit PIXEL=33", 4)
    HSI_33 = ("HSI 8-bit PIXEL=33", 3)
    CCT_RGB_11 = ("CCT&RGB 8-bit PIXEL=11", 21)
    CCT_HSI_11 = ("CCT&HSI 8-bit PIXEL=11", 18)
    CCT_11 = ("CCT 8-bit PIXEL=11", 9)
    RGB_11 = ("RGB 8-bit PIXEL=11", 12)
    HSI_11 = ("HSI 8-bit PIXEL=11", 9)
    CCT_RGB_3 = ("CCT&RGB 8-bit PIXEL=3", 77)
    CCT_HSI_3 = ("CCT&HSI 8-bit PIXEL=3", 66)
    CCT_3 = ("CCT 8-bit PIXEL=3", 33)
    RGB_3 = ("RGB 8-bit PIXEL=3", 44)
    HSI_3 = ("HSI 8-bit PIXEL=3", 33)
    CCT_RGB_1 = ("CCT&RGB 8-bit PIXEL=1", 231)
    CCT_HSI_1 = ("CCT&HSI 8-bit PIXEL=1", 198)
    CCT_1 = ("CCT 8-bit PIXEL=1", 99)
    RGB_1 = ("RGB 8-bit PIXEL=1", 132)
    HSI_1 = ("HSI 8-bit PIXEL=1", 99)
    EFFECT = ("EFFECT 8-bit", 5)
    PIXEL_FX = ("PIXEL FX 8-bit", 9)

    def __init__(self, description: str, channels: int):
        self.description = description
        self.channels = channels


@dataclass
class ColorRGB:
    """RGB color representation"""
    r: int = 0  # 0-255
    g: int = 0  # 0-255
    b: int = 0  # 0-255
    
    def to_tuple(self) -> Tuple[int, int, int]:
        return (self.r, self.g, self.b)


@dataclass
class ColorHSI:
    """HSI color representation"""
    h: float = 0.0  # 0.0-360.0 degrees
    s: float = 0.0  # 0.0-100.0 percent
    i: float = 0.0  # 0.0-100.0 percent (intensity)
    
    def to_dmx_values(self) -> Tuple[int, int]:
        """Convert to DMX values (HUE: 0-255, SAT: 0-255)"""
        hue_dmx = int((self.h / 360.0) * 255)
        sat_dmx = int((self.s / 100.0) * 255)
        return (hue_dmx, sat_dmx)


@dataclass
class ColorCCT:
    """CCT (Correlated Color Temperature) representation"""
    cct: int = 5600  # 2700K-10000K
    gm: int = 0      # Green/Magenta shift: -50 to +50
    
    def to_dmx_values(self) -> Tuple[int, int]:
        """Convert to DMX values"""
        # Map 2700-10000K to 0-255
        cct_dmx = int(((self.cct - 2700) / (10000 - 2700)) * 255)
        # Map -50 to +50 to 0-255
        gm_dmx = int(((self.gm + 50) / 100) * 255)
        return (cct_dmx, gm_dmx)


class GVMEffectType(Enum):
    """Built-in effect types"""
    OFF = (0, "OFF")
    LIGHTNING = (15, "Lightning")
    CCT_LOOP = (25, "CCT Loop")
    CANDLE = (35, "Candle")
    BAD_BULB = (45, "Bad Bulb")
    TV = (55, "TV")
    PAPARAZZI = (65, "Paparazzi")
    EXPLOSION = (75, "Explosion")
    PULSING = (85, "Pulsing")
    DISCO = (95, "Disco")
    COP_CAR = (105, "Cop Car")
    PARTY = (115, "Party")
    HUE_LOOP = (125, "Hue Loop")
    
    def __init__(self, dmx_value: int, description: str):
        self.dmx_value = dmx_value
        self.description = description


class GVMPixelFXType(Enum):
    """Pixel effect types"""
    ROLLING = (5, "Rolling")
    RAINBOW = (15, "Rainbow")
    BLOCKGAME = (25, "BlockGame")
    PINGPONG = (35, "PingPong")
    WAVE = (45, "Wave")
    METEOR = (55, "Meteor")
    
    def __init__(self, dmx_value: int, description: str):
        self.dmx_value = dmx_value
        self.description = description


class GVMLightController:
    """
    Controller for GVM GVM-PRO-BD45R light
    Handles all DMX modes and provides high-level lighting control
    """
    
    def __init__(self, dmx_controller: EnttecOpenDMX, start_channel: int = 1):
        """
        Initialize GVM light controller
        
        Args:
            dmx_controller: DMX interface controller
            start_channel: Starting DMX channel (1-512)
        """
        self.dmx = dmx_controller
        self.start_channel = start_channel
        self.current_mode = GVMMode.RGB_33  # Default to simple RGB mode
        self.master_intensity = 100  # 0-100%
        
        # Current color state
        self.rgb_color = ColorRGB(255, 255, 255)
        self.hsi_color = ColorHSI(0, 0, 100)
        self.cct_color = ColorCCT(5600, 0)
        
        # Effect state
        self.current_effect = GVMEffectType.OFF
        self.effect_speed = 5  # 1-10
        self.effect_control = False  # Loop/Stop
        
        # Pixel FX state
        self.pixel_fx = GVMPixelFXType.ROLLING
        self.pixel_fx_speed = 5
        self.pixel_fx_direction = 0  # 0=left, 1=right
        
    def set_mode(self, mode: GVMMode):
        """Change the DMX mode and update light accordingly"""
        self.current_mode = mode
        logger.info(f"Changed to mode: {mode.description} ({mode.channels} channels)")
        self._update_light()
    
    def set_master_intensity(self, intensity: float):
        """
        Set master intensity
        
        Args:
            intensity: Intensity percentage (0-100)
        """
        self.master_intensity = max(0, min(100, intensity))
        self._update_light()
    
    def set_rgb_color(self, r: int, g: int, b: int, intensity: float = None):
        """
        Set RGB color
        
        Args:
            r, g, b: RGB values (0-255)
            intensity: Optional intensity override (0-100)
        """
        self.rgb_color = ColorRGB(
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b))
        )
        
        if intensity is not None:
            self.master_intensity = max(0, min(100, intensity))
            
        self._update_light()
    
    def set_hsi_color(self, hue: float, saturation: float, intensity: float = None):
        """
        Set HSI color
        
        Args:
            hue: Hue in degrees (0-360)
            saturation: Saturation percentage (0-100)
            intensity: Optional intensity override (0-100)
        """
        self.hsi_color = ColorHSI(
            hue % 360,
            max(0, min(100, saturation)),
            self.master_intensity if intensity is None else max(0, min(100, intensity))
        )
        
        if intensity is not None:
            self.master_intensity = intensity
            
        self._update_light()
    
    def set_cct_color(self, cct: int, gm: int = 0, intensity: float = None):
        """
        Set CCT color temperature
        
        Args:
            cct: Color temperature (2700-10000K)
            gm: Green/Magenta shift (-50 to +50)
            intensity: Optional intensity override (0-100)
        """
        self.cct_color = ColorCCT(
            max(2700, min(10000, cct)),
            max(-50, min(50, gm))
        )
        
        if intensity is not None:
            self.master_intensity = max(0, min(100, intensity))
            
        self._update_light()
    
    def set_effect(self, effect: GVMEffectType, speed: int = 5, loop: bool = True):
        """
        Set built-in effect
        
        Args:
            effect: Effect type
            speed: Effect speed (1-10)
            loop: Whether to loop the effect
        """
        self.current_effect = effect
        self.effect_speed = max(1, min(10, speed))
        self.effect_control = loop
        
        # Switch to effect mode
        self.current_mode = GVMMode.EFFECT
        self._update_light()
    
    def set_pixel_effect(self, fx: GVMPixelFXType, speed: int = 5, direction: int = 0):
        """
        Set pixel effect
        
        Args:
            fx: Pixel effect type
            speed: Effect speed (1-10)
            direction: Direction (0=left, 1=right)
        """
        self.pixel_fx = fx
        self.pixel_fx_speed = max(1, min(10, speed))
        self.pixel_fx_direction = direction
        
        # Switch to pixel FX mode
        self.current_mode = GVMMode.PIXEL_FX
        self._update_light()
    
    def off(self):
        """Turn off the light"""
        self.master_intensity = 0
        self._update_light()
    
    def full_white(self, intensity: float = 100):
        """Set to full white at specified intensity"""
        self.set_rgb_color(255, 255, 255, intensity)
    
    def _update_light(self):
        """Update the DMX channels based on current state"""
        if not self.dmx.is_connected:
            logger.warning("DMX controller not connected")
            return
            
        # Clear channels for this fixture
        for i in range(self.current_mode.channels):
            self.dmx.set_channel(self.start_channel + i, 0)
        
        # Set channels based on current mode
        if self.current_mode == GVMMode.RGB_33:
            self._update_rgb_mode()
        elif self.current_mode == GVMMode.HSI_33:
            self._update_hsi_mode()
        elif self.current_mode == GVMMode.CCT_33:
            self._update_cct_mode()
        elif self.current_mode == GVMMode.CCT_RGB_33:
            self._update_cct_rgb_mode()
        elif self.current_mode == GVMMode.CCT_HSI_33:
            self._update_cct_hsi_mode()
        elif self.current_mode == GVMMode.EFFECT:
            self._update_effect_mode()
        elif self.current_mode == GVMMode.PIXEL_FX:
            self._update_pixel_fx_mode()
        else:
            logger.warning(f"Mode {self.current_mode.description} not implemented yet")
    
    def _update_rgb_mode(self):
        """Update channels for RGB mode (4 channels)"""
        intensity_dmx = int((self.master_intensity / 100.0) * 255)
        
        channels = {
            self.start_channel: intensity_dmx,      # Intensity
            self.start_channel + 1: self.rgb_color.r,  # Red
            self.start_channel + 2: self.rgb_color.g,  # Green
            self.start_channel + 3: self.rgb_color.b   # Blue
        }
        
        self.dmx.set_channels(channels)
    
    def _update_hsi_mode(self):
        """Update channels for HSI mode (3 channels)"""
        intensity_dmx = int((self.master_intensity / 100.0) * 255)
        hue_dmx, sat_dmx = self.hsi_color.to_dmx_values()
        
        channels = {
            self.start_channel: intensity_dmx,      # Intensity
            self.start_channel + 1: hue_dmx,        # Hue
            self.start_channel + 2: sat_dmx         # Saturation
        }
        
        self.dmx.set_channels(channels)
    
    def _update_cct_mode(self):
        """Update channels for CCT mode (3 channels)"""
        intensity_dmx = int((self.master_intensity / 100.0) * 255)
        cct_dmx, gm_dmx = self.cct_color.to_dmx_values()
        
        channels = {
            self.start_channel: intensity_dmx,      # Intensity
            self.start_channel + 1: cct_dmx,        # CCT
            self.start_channel + 2: gm_dmx          # Green/Magenta
        }
        
        self.dmx.set_channels(channels)
    
    def _update_cct_rgb_mode(self):
        """Update channels for CCT&RGB mode (7 channels)"""
        intensity_dmx = int((self.master_intensity / 100.0) * 255)

        # Set stable CCT values (5600K daylight, no GM shift)
        cct_dmx = 127  # Middle value for 5600K
        gm_dmx = 127   # No green/magenta shift

        channels = {
            self.start_channel: intensity_dmx,      # Intensity
            self.start_channel + 1: cct_dmx,        # CCT (stable value)
            self.start_channel + 2: gm_dmx,         # Green/Magenta (neutral)
            self.start_channel + 3: 255,            # CCT<->RGB crossfade (100% RGB)
            self.start_channel + 4: self.rgb_color.r,  # Red
            self.start_channel + 5: self.rgb_color.g,  # Green
            self.start_channel + 6: self.rgb_color.b   # Blue
        }

        self.dmx.set_channels(channels)
    
    def _update_cct_hsi_mode(self):
        """Update channels for CCT&HSI mode (6 channels)"""
        intensity_dmx = int((self.master_intensity / 100.0) * 255)
        cct_dmx, gm_dmx = self.cct_color.to_dmx_values()
        hue_dmx, sat_dmx = self.hsi_color.to_dmx_values()
        
        channels = {
            self.start_channel: intensity_dmx,      # Intensity
            self.start_channel + 1: cct_dmx,        # CCT
            self.start_channel + 2: gm_dmx,         # Green/Magenta
            self.start_channel + 3: 127,            # CCT<->HSI crossfade (50%)
            self.start_channel + 4: hue_dmx,        # Hue
            self.start_channel + 5: sat_dmx         # Saturation
        }
        
        self.dmx.set_channels(channels)
    
    def _update_effect_mode(self):
        """Update channels for effect mode (5 channels)"""
        intensity_dmx = int((self.master_intensity / 100.0) * 255)
        speed_dmx = int(((self.effect_speed - 1) / 9.0) * 90) + 10  # Map 1-10 to 10-99
        
        channels = {
            self.start_channel: intensity_dmx,              # Intensity
            self.start_channel + 1: self.current_effect.dmx_value,  # Effect type
            self.start_channel + 2: 127 if self.effect_control else 255,  # Control (loop/stop)
            self.start_channel + 3: speed_dmx,              # Speed
            self.start_channel + 4: 127                     # Parameter (depends on effect)
        }
        
        self.dmx.set_channels(channels)
    
    def _update_pixel_fx_mode(self):
        """Update channels for pixel FX mode (9 channels)"""
        intensity_dmx = int((self.master_intensity / 100.0) * 255)
        speed_dmx = int(((self.pixel_fx_speed - 1) / 9.0) * 90) + 10
        direction_dmx = 255 if self.pixel_fx_direction else 127
        
        channels = {
            self.start_channel: intensity_dmx,              # Intensity
            self.start_channel + 1: self.pixel_fx.dmx_value,    # FX type
            self.start_channel + 2: 255,                    # FX status (run)
            self.start_channel + 3: speed_dmx,              # Speed
            self.start_channel + 4: direction_dmx,          # Direction
            # Channels 6-9 are parameters (simplified for now)
            self.start_channel + 5: 0,                      # Color mode
            self.start_channel + 6: 5,                      # Rolling pixels
            self.start_channel + 7: 127,                    # Parameter 1
            self.start_channel + 8: 127                     # Parameter 2
        }
        
        self.dmx.set_channels(channels)


class GVMLiftingCastIntegration(LightingSignalHandler):
    """
    Integration layer for LiftingCast WebSocket signals
    This will be the main interface for external control
    """
    
    def __init__(self, dmx_controller: EnttecOpenDMX, gvm_controller: GVMLightController):
        super().__init__(dmx_controller)
        self.gvm = gvm_controller
        
        # Register signal handlers for LiftingCast
        self.register_signal_callback('color_change', self._handle_color_change)
        self.register_signal_callback('intensity_change', self._handle_intensity_change)
        self.register_signal_callback('effect_trigger', self._handle_effect_trigger)
        self.register_signal_callback('emergency_red', self._handle_emergency_red)
        self.register_signal_callback('all_clear', self._handle_all_clear)
    
    def _handle_color_change(self, data: Dict):
        """Handle color change signals from LiftingCast"""
        if 'rgb' in data:
            r, g, b = data['rgb']
            intensity = data.get('intensity', self.gvm.master_intensity)
            self.gvm.set_rgb_color(r, g, b, intensity)
            logger.info(f"Color changed to RGB({r}, {g}, {b}) @ {intensity}%")
            
        elif 'hsi' in data:
            h, s, i = data['hsi']
            self.gvm.set_hsi_color(h, s, i)
            logger.info(f"Color changed to HSI({h}, {s}, {i})")
            
        elif 'cct' in data:
            cct = data['cct']
            gm = data.get('gm', 0)
            intensity = data.get('intensity', self.gvm.master_intensity)
            self.gvm.set_cct_color(cct, gm, intensity)
            logger.info(f"Color changed to CCT({cct}K, GM:{gm}) @ {intensity}%")
    
    def _handle_intensity_change(self, data: Dict):
        """Handle intensity change signals"""
        intensity = data.get('intensity', 100)
        self.gvm.set_master_intensity(intensity)
        logger.info(f"Intensity changed to {intensity}%")
    
    def _handle_effect_trigger(self, data: Dict):
        """Handle effect trigger signals"""
        effect_name = data.get('effect', 'lightning')
        speed = data.get('speed', 5)
        
        # Map effect names to GVM effects
        effect_map = {
            'lightning': GVMEffectType.LIGHTNING,
            'candle': GVMEffectType.CANDLE,
            'strobe': GVMEffectType.PAPARAZZI,
            'explosion': GVMEffectType.EXPLOSION,
            'tv': GVMEffectType.TV
        }
        
        effect = effect_map.get(effect_name, GVMEffectType.LIGHTNING)
        self.gvm.set_effect(effect, speed)
        logger.info(f"Effect triggered: {effect_name}")
    
    def _handle_emergency_red(self, data: Dict):
        """Handle emergency red signal"""
        self.gvm.set_rgb_color(255, 0, 0, 100)  # Full red
        logger.warning("EMERGENCY RED activated")
    
    def _handle_all_clear(self, data: Dict):
        """Handle all clear signal"""
        self.gvm.full_white(50)  # Return to white at 50%
        logger.info("All clear - returning to normal")


# Utility functions for color conversion
def rgb_to_hsi(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """Convert RGB to HSI"""
    r_norm, g_norm, b_norm = r/255.0, g/255.0, b/255.0
    h, s, v = colorsys.rgb_to_hsv(r_norm, g_norm, b_norm)
    i = (r_norm + g_norm + b_norm) / 3.0
    return (h * 360, s * 100, i * 100)


def hsi_to_rgb(h: float, s: float, i: float) -> Tuple[int, int, int]:
    """Convert HSI to RGB"""
    h_norm, s_norm, i_norm = h/360.0, s/100.0, i/100.0
    r, g, b = colorsys.hsv_to_rgb(h_norm, s_norm, i_norm)
    return (int(r * 255), int(g * 255), int(b * 255))


if __name__ == "__main__":
    # Basic test
    print("GVM Light Controller initialized")