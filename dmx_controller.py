#!/usr/bin/env python3
"""
DMX Controller for Enttec Open DMX USB
Designed for integration with LiftingCast websocket signals
"""

import serial
import time
import threading
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DMXError(Exception):
    """Custom exception for DMX-related errors"""
    pass


@dataclass
class DMXFrame:
    """Represents a complete DMX frame"""
    start_code: int = 0
    channels: bytearray = None
    
    def __post_init__(self):
        if self.channels is None:
            self.channels = bytearray(512)  # Initialize 512 channels to 0


class EnttecOpenDMX:
    """
    Enttec Open DMX USB controller interface
    Handles low-level USB/Serial communication for DMX transmission.

    Channel writes only change the frame in memory; the transmission thread sends a
    snapshot of it 30 times a second. Writes and snapshots share a lock, and a fixture
    groups its writes with batch(), so a frame never goes out half-updated. If the USB
    link fails, the thread keeps running and reopens the port until it comes back.
    """

    RECONNECT_SECONDS = 2.0

    def __init__(self, port: str = None, baud_rate: int = 250000):
        """
        Initialize the DMX controller

        Args:
            port: Serial port path (e.g., '/dev/tty.usbserial-EN123456' on Mac); None = auto-detect
            baud_rate: Serial baud rate (250000 for DMX512)
        """
        self.port = port
        self.auto_detect = port is None
        self.baud_rate = baud_rate
        self.serial_connection: Optional[serial.Serial] = None
        self.is_connected = False
        self.is_transmitting = False
        self.transmission_thread: Optional[threading.Thread] = None
        self.frame_rate = 30  # Default 30 FPS
        self.current_frame = DMXFrame()
        self._stop_transmission = threading.Event()
        self._frame_lock = threading.RLock()
        self._frame_count = 0
        self._rate_since: Optional[float] = None

    def find_enttec_port(self) -> Optional[str]:
        """
        Automatically find the Enttec Open DMX USB port
        Returns the port path if found, None otherwise
        """
        import serial.tools.list_ports

        for port in serial.tools.list_ports.comports():
            # Look for FTDI devices (Enttec uses FTDI chips)
            if 'FTDI' in port.description or 'FT232' in port.description:
                logger.info(f"Found potential Enttec device: {port.device} - {port.description}")
                return port.device

        logger.warning("No Enttec device found automatically")
        return None

    def _open(self) -> None:
        """Open the serial port; raises serial.SerialException / OSError on failure."""
        self.serial_connection = serial.Serial(
            port=self.port,
            baudrate=self.baud_rate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_TWO,
            timeout=1.0
        )
        # Configure for DMX transmission
        self.serial_connection.rts = False  # RTS low for transmit mode
        self.serial_connection.dtr = False
        self.is_connected = True

    def _close_port(self) -> None:
        self.is_connected = False
        conn, self.serial_connection = self.serial_connection, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def connect(self, port: str = None) -> bool:
        """
        Connect to the DMX interface

        Args:
            port: Override the default port

        Returns:
            True if connection successful, False otherwise
        """
        if port:
            self.port = port
            self.auto_detect = False

        if not self.port:
            self.port = self.find_enttec_port()

        if not self.port:
            raise DMXError("No DMX port specified and auto-detection failed")

        try:
            self._open()
            logger.info(f"Connected to DMX interface on {self.port}")
            return True
        except (serial.SerialException, OSError) as e:
            logger.error(f"Failed to connect to DMX interface: {e}")
            self._close_port()
            return False

    def _reconnect(self) -> bool:
        """One attempt to reopen the port after a failure."""
        self._close_port()
        if self.auto_detect:
            self.port = self.find_enttec_port() or self.port
        try:
            self._open()
            return True
        except (serial.SerialException, OSError):
            self._close_port()
            return False

    def disconnect(self):
        """Disconnect from the DMX interface"""
        self.stop_transmission()
        self._close_port()
        logger.info("Disconnected from DMX interface")

    def batch(self):
        """Hold the frame lock across several channel writes, so the transmission
        thread sends all of them or none of them: `with dmx.batch(): ...`"""
        return self._frame_lock

    def send_frame(self, frame: DMXFrame = None):
        """
        Send a single DMX frame

        Args:
            frame: DMX frame to send, uses current_frame if None
        """
        if not self.is_connected or not self.serial_connection:
            raise DMXError("Not connected to DMX interface")

        if frame is None:
            frame = self.current_frame

        with self._frame_lock:
            packet = bytes([frame.start_code]) + bytes(frame.channels)

        try:
            # BREAK, then MARK AFTER BREAK. Not send_break(): on Linux and macOS
            # tcsendbreak ignores the duration and holds the line 0.25-0.5s, which
            # caps output near 2-3 frames/sec. Receivers accept a long-ish break.
            self.serial_connection.break_condition = True
            time.sleep(0.001)
            self.serial_connection.break_condition = False
            time.sleep(0.000012)

            self.serial_connection.write(packet)
            # write() returns once the bytes are queued, not sent. Wait for them to go
            # out, or the next frame's break would cut off the end of this one.
            self.serial_connection.flush()
        except (serial.SerialException, OSError) as e:
            raise DMXError(f"Failed to send DMX frame: {e}")

        self._frame_count += 1
        self._report_rate()

    def _report_rate(self):
        """A heartbeat in the log: the real frame rate after the first minute, then every
        10 minutes (the frame dump it replaces was a line a second)."""
        now = time.monotonic()
        if self._rate_since is None:
            self._rate_since, self._rate_frames, self._rate_every = now, self._frame_count, 60.0
            return
        elapsed = now - self._rate_since
        if elapsed >= self._rate_every:
            fps = (self._frame_count - self._rate_frames) / elapsed
            logger.info(f"DMX output: {fps:.1f} frames/s")
            self._rate_since, self._rate_frames, self._rate_every = now, self._frame_count, 600.0

    def start_transmission(self):
        """Start continuous DMX frame transmission in a background thread"""
        if self.is_transmitting:
            logger.warning("Transmission already active")
            return

        if not self.is_connected:
            raise DMXError("Not connected to DMX interface")

        self._stop_transmission.clear()
        self.is_transmitting = True
        self.transmission_thread = threading.Thread(target=self._transmission_loop)
        self.transmission_thread.daemon = True
        self.transmission_thread.start()
        logger.info(f"Started DMX transmission at {self.frame_rate} FPS")

    def stop_transmission(self):
        """Stop continuous DMX frame transmission"""
        if not self.is_transmitting:
            return

        self._stop_transmission.set()

        if self.transmission_thread:
            self.transmission_thread.join(timeout=2.0)

        self.is_transmitting = False
        logger.info("Stopped DMX transmission")

    def _transmission_loop(self):
        """Internal transmission loop for background thread. Never gives up: a USB error
        closes the port and it is reopened every RECONNECT_SECONDS until it works."""
        while not self._stop_transmission.is_set():
            start_time = time.time()

            if not self.is_connected:
                if self._reconnect():
                    logger.info(f"DMX interface back on {self.port}")
                    self._rate_since = None
                else:
                    self._stop_transmission.wait(self.RECONNECT_SECONDS)
                    continue

            try:
                self.send_frame()
            except Exception as e:  # any failure here must not end the thread
                logger.error(f"DMX output lost ({e}); retrying every {self.RECONNECT_SECONDS:g}s")
                self._close_port()
                continue

            # Maintain frame rate
            sleep_time = 1.0 / self.frame_rate - (time.time() - start_time)
            if sleep_time > 0:
                self._stop_transmission.wait(sleep_time)

    def set_channel(self, channel: int, value: int):
        """
        Set a single DMX channel value

        Args:
            channel: Channel number (1-512)
            value: Channel value (0-255)
        """
        if not 1 <= channel <= 512:
            raise ValueError(f"Channel must be 1-512, got {channel}")

        if not 0 <= value <= 255:
            raise ValueError(f"Value must be 0-255, got {value}")

        with self._frame_lock:
            self.current_frame.channels[channel - 1] = value

    def set_channels(self, channels: Dict[int, int]):
        """
        Set multiple DMX channel values (all sent in the same frame)

        Args:
            channels: Dictionary mapping channel numbers to values
        """
        with self._frame_lock:
            for channel, value in channels.items():
                self.set_channel(channel, value)

    def get_channel(self, channel: int) -> int:
        """
        Get current value of a DMX channel

        Args:
            channel: Channel number (1-512)

        Returns:
            Current channel value (0-255)
        """
        if not 1 <= channel <= 512:
            raise ValueError(f"Channel must be 1-512, got {channel}")

        return self.current_frame.channels[channel - 1]

    def clear_all_channels(self):
        """Set all channels to 0"""
        with self._frame_lock:
            self.current_frame.channels = bytearray(512)

    def set_frame_rate(self, fps: int):
        """
        Set DMX transmission frame rate
        
        Args:
            fps: Frames per second (1-44, as per Enttec spec)
        """
        if not 1 <= fps <= 44:
            raise ValueError(f"Frame rate must be 1-44 FPS, got {fps}")
            
        self.frame_rate = fps
        logger.info(f"Frame rate set to {fps} FPS")


class LightingSignalHandler:
    """
    Interface for handling lighting signals from external sources (like LiftingCast)
    This class will be extended for WebSocket integration
    """
    
    def __init__(self, dmx_controller: EnttecOpenDMX):
        self.dmx_controller = dmx_controller
        self.signal_callbacks: Dict[str, Callable] = {}
    
    def register_signal_callback(self, signal_type: str, callback: Callable):
        """
        Register a callback for a specific signal type
        
        Args:
            signal_type: Type of signal (e.g., 'color_change', 'intensity_change')
            callback: Function to call when signal is received
        """
        self.signal_callbacks[signal_type] = callback
        logger.info(f"Registered callback for signal type: {signal_type}")
    
    def process_signal(self, signal_type: str, data: Dict[str, Any]):
        """
        Process an incoming signal
        
        Args:
            signal_type: Type of signal received
            data: Signal data payload
        """
        if signal_type in self.signal_callbacks:
            try:
                self.signal_callbacks[signal_type](data)
            except Exception as e:
                logger.error(f"Error processing signal {signal_type}: {e}")
        else:
            logger.warning(f"No handler registered for signal type: {signal_type}")


# Example usage and testing functions
def test_dmx_connection(port: str = None):
    """Test basic DMX connection and transmission"""
    dmx = EnttecOpenDMX(port=port)
    
    try:
        # Connect
        if not dmx.connect():
            print("Failed to connect to DMX interface")
            return False
            
        print(f"Connected to DMX interface on {dmx.port}")
        
        # Test single frame
        dmx.set_channel(1, 255)  # Set channel 1 to full
        dmx.send_frame()
        print("Sent test frame")
        
        # Test continuous transmission
        dmx.start_transmission()
        print("Started continuous transmission")
        
        # Let it run for a few seconds
        time.sleep(3)
        
        # Stop transmission
        dmx.stop_transmission()
        dmx.disconnect()
        
        print("DMX test completed successfully")
        return True
        
    except Exception as e:
        print(f"DMX test failed: {e}")
        dmx.disconnect()
        return False


if __name__ == "__main__":
    # Basic test when run directly
    print("Testing DMX Controller...")
    test_dmx_connection()