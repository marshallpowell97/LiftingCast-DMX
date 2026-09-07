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
    Handles low-level USB/Serial communication for DMX transmission
    """
    
    def __init__(self, port: str = None, baud_rate: int = 250000):
        """
        Initialize the DMX controller
        
        Args:
            port: Serial port path (e.g., '/dev/tty.usbserial-EN123456' on Mac)
            baud_rate: Serial baud rate (250000 for DMX512)
        """
        self.port = port
        self.baud_rate = baud_rate
        self.serial_connection: Optional[serial.Serial] = None
        self.is_connected = False
        self.is_transmitting = False
        self.transmission_thread: Optional[threading.Thread] = None
        self.frame_rate = 30  # Default 30 FPS
        self.current_frame = DMXFrame()
        self._stop_transmission = threading.Event()
        
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
            
        if not self.port:
            self.port = self.find_enttec_port()
            
        if not self.port:
            raise DMXError("No DMX port specified and auto-detection failed")
            
        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_TWO,
                timeout=1.0
            )
            
            # Configure for DMX transmission
            self.serial_connection.setRTS(False)  # RTS low for transmit mode
            self.serial_connection.setDTR(False)
            
            self.is_connected = True
            logger.info(f"Connected to DMX interface on {self.port}")
            return True
            
        except serial.SerialException as e:
            logger.error(f"Failed to connect to DMX interface: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """Disconnect from the DMX interface"""
        self.stop_transmission()
        
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            
        self.is_connected = False
        logger.info("Disconnected from DMX interface")
    
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

        try:
            # Send BREAK (by setting break condition)
            self.serial_connection.send_break(duration=0.000088)  # 88µs break

            # Send MARK AFTER BREAK (MAB) - brief high period
            time.sleep(0.000008)  # 8µs MAB

            # Send START CODE
            self.serial_connection.write(bytes([frame.start_code]))

            # Send CHANNEL DATA
            self.serial_connection.write(frame.channels)

            # Debug: Log the first 8 channels every 30 frames
            if hasattr(self, '_frame_count'):
                self._frame_count += 1
            else:
                self._frame_count = 1

            if self._frame_count % 30 == 0:  # Every 30 frames (every 6 seconds at 5fps)
                ch_data = [frame.channels[i] for i in range(8)]
                logger.info(f"DMX Frame #{self._frame_count}: Start={frame.start_code}, Channels 1-8: {ch_data}")

        except serial.SerialException as e:
            logger.error(f"Error sending DMX frame: {e}")
            raise DMXError(f"Failed to send DMX frame: {e}")
    
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
            self.transmission_thread.join(timeout=1.0)
            
        self.is_transmitting = False
        logger.info("Stopped DMX transmission")
    
    def _transmission_loop(self):
        """Internal transmission loop for background thread"""
        frame_interval = 1.0 / self.frame_rate
        
        while not self._stop_transmission.is_set():
            start_time = time.time()
            
            try:
                self.send_frame()
            except DMXError as e:
                logger.error(f"Transmission error: {e}")
                break
                
            # Maintain frame rate
            elapsed = time.time() - start_time
            sleep_time = frame_interval - elapsed
            
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
            
        self.current_frame.channels[channel - 1] = value
    
    def set_channels(self, channels: Dict[int, int]):
        """
        Set multiple DMX channel values
        
        Args:
            channels: Dictionary mapping channel numbers to values
        """
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