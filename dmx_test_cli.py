#!/usr/bin/env python3
"""
Command Line Interface for testing DMX and GVM light control
Provides interactive testing and demonstration capabilities
"""

import argparse
import time
import sys
import json
from typing import Optional, Dict, Any
import logging

from dmx_controller import EnttecOpenDMX, test_dmx_connection
from gvm_light_controller import (
    GVMLightController, GVMMode, GVMEffectType, GVMPixelFXType,
    ColorRGB, ColorHSI, ColorCCT, GVMLiftingCastIntegration,
    rgb_to_hsi, hsi_to_rgb
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DMXTestCLI:
    """Command-line interface for DMX testing"""
    
    def __init__(self, port: str = None, start_channel: int = 1):
        """Initialize the CLI with DMX controller and GVM light"""
        self.dmx = EnttecOpenDMX(port=port)
        self.gvm: Optional[GVMLightController] = None
        self.integration: Optional[GVMLiftingCastIntegration] = None
        self.start_channel = start_channel
        self.connected = False
        
    def connect(self, port: str = None) -> bool:
        """Connect to DMX interface"""
        if port:
            self.dmx.port = port
            
        try:
            if self.dmx.connect():
                self.connected = True
                self.gvm = GVMLightController(self.dmx, self.start_channel)
                self.integration = GVMLiftingCastIntegration(self.dmx, self.gvm)
                print(f"✓ Connected to DMX interface on {self.dmx.port}")
                print(f"✓ GVM light controller initialized (channel {self.start_channel})")
                return True
            else:
                print("✗ Failed to connect to DMX interface")
                return False
        except Exception as e:
            print(f"✗ Connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from DMX interface"""
        if self.dmx:
            self.dmx.disconnect()
        self.connected = False
        print("✓ Disconnected")
    
    def start_transmission(self):
        """Start continuous DMX transmission"""
        if not self.connected:
            print("✗ Not connected to DMX interface")
            return
            
        self.dmx.start_transmission()
        print("✓ Started continuous DMX transmission")
    
    def stop_transmission(self):
        """Stop DMX transmission"""
        if self.dmx:
            self.dmx.stop_transmission()
        print("✓ Stopped DMX transmission")
    
    def test_basic_dmx(self):
        """Test basic DMX functionality"""
        print("Testing basic DMX functionality...")
        
        if not self.connected:
            print("✗ Not connected")
            return
            
        # Test setting individual channels
        print("Setting channels 1-3 to full (255)...")
        self.dmx.set_channels({1: 255, 2: 255, 3: 255})
        self.dmx.send_frame()
        time.sleep(2)
        
        print("Setting channels 1-3 to half (127)...")
        self.dmx.set_channels({1: 127, 2: 127, 3: 127})
        self.dmx.send_frame()
        time.sleep(2)
        
        print("Clearing all channels...")
        self.dmx.clear_all_channels()
        self.dmx.send_frame()
        
        print("✓ Basic DMX test completed")
    
    def test_gvm_modes(self):
        """Test different GVM modes"""
        if not self.gvm:
            print("✗ GVM controller not initialized")
            return
            
        print("Testing GVM modes...")
        
        # Test RGB mode
        print("Testing RGB mode...")
        self.gvm.set_mode(GVMMode.RGB_33)
        self.gvm.set_rgb_color(255, 0, 0, 100)  # Red
        time.sleep(2)
        self.gvm.set_rgb_color(0, 255, 0, 100)  # Green
        time.sleep(2)
        self.gvm.set_rgb_color(0, 0, 255, 100)  # Blue
        time.sleep(2)
        
        # Test HSI mode
        print("Testing HSI mode...")
        self.gvm.set_mode(GVMMode.HSI_33)
        self.gvm.set_hsi_color(0, 100, 100)     # Red
        time.sleep(2)
        self.gvm.set_hsi_color(120, 100, 100)   # Green
        time.sleep(2)
        self.gvm.set_hsi_color(240, 100, 100)   # Blue
        time.sleep(2)
        
        # Test CCT mode
        print("Testing CCT mode...")
        self.gvm.set_mode(GVMMode.CCT_33)
        self.gvm.set_cct_color(3200, 0, 100)    # Warm white
        time.sleep(2)
        self.gvm.set_cct_color(5600, 0, 100)    # Daylight
        time.sleep(2)
        self.gvm.set_cct_color(8000, 0, 100)    # Cool white
        time.sleep(2)
        
        print("✓ GVM mode test completed")
    
    def test_effects(self):
        """Test built-in effects"""
        if not self.gvm:
            print("✗ GVM controller not initialized")
            return
            
        print("Testing effects...")
        
        effects_to_test = [
            GVMEffectType.LIGHTNING,
            GVMEffectType.CANDLE,
            GVMEffectType.TV,
            GVMEffectType.PULSING
        ]
        
        for effect in effects_to_test:
            print(f"Testing {effect.description}...")
            self.gvm.set_effect(effect, speed=7)
            time.sleep(5)
        
        # Return to normal
        self.gvm.set_mode(GVMMode.RGB_33)
        self.gvm.full_white(50)
        
        print("✓ Effects test completed")
    
    def color_demo(self):
        """Demonstrate smooth color transitions"""
        if not self.gvm:
            print("✗ GVM controller not initialized")
            return
            
        print("Running color demo...")
        self.gvm.set_mode(GVMMode.HSI_33)
        
        # Hue cycle
        print("Cycling through hues...")
        for hue in range(0, 360, 10):
            self.gvm.set_hsi_color(hue, 100, 100)
            time.sleep(0.1)
        
        # Saturation fade
        print("Fading saturation...")
        for sat in range(100, -1, -5):
            self.gvm.set_hsi_color(0, sat, 100)  # Red hue
            time.sleep(0.1)
        
        # Intensity fade
        print("Fading intensity...")
        for intensity in range(100, -1, -5):
            self.gvm.set_hsi_color(0, 100, intensity)
            time.sleep(0.1)
        
        print("✓ Color demo completed")
    
    def simulate_liftingcast_signals(self):
        """Simulate LiftingCast WebSocket signals"""
        if not self.integration:
            print("✗ LiftingCast integration not initialized")
            return
            
        print("Simulating LiftingCast signals...")
        
        # Normal operation
        print("Simulating normal operation (white light)...")
        self.integration.process_signal('color_change', {
            'rgb': (255, 255, 255),
            'intensity': 75
        })
        time.sleep(3)
        
        # Alert condition
        print("Simulating alert condition (yellow)...")
        self.integration.process_signal('color_change', {
            'rgb': (255, 255, 0),
            'intensity': 100
        })
        time.sleep(3)
        
        # Emergency
        print("Simulating emergency...")
        self.integration.process_signal('emergency_red', {})
        time.sleep(5)
        
        # Effect trigger
        print("Simulating effect trigger...")
        self.integration.process_signal('effect_trigger', {
            'effect': 'lightning',
            'speed': 8
        })
        time.sleep(5)
        
        # All clear
        print("Simulating all clear...")
        self.integration.process_signal('all_clear', {})
        time.sleep(3)
        
        print("✓ LiftingCast simulation completed")
    
    def interactive_mode(self):
        """Interactive control mode"""
        if not self.gvm:
            print("✗ GVM controller not initialized")
            return
            
        print("\n=== Interactive GVM Light Control ===")
        print("Commands:")
        print("  rgb R G B [I]    - Set RGB color (0-255) with optional intensity (0-100)")
        print("  hsi H S I        - Set HSI color (H:0-360, S:0-100, I:0-100)")
        print("  cct T [GM] [I]   - Set CCT (T:2700-10000K, GM:-50-50, I:0-100)")
        print("  intensity I      - Set intensity (0-100)")
        print("  mode MODE        - Set mode (rgb, hsi, cct, effect, pixelfx)")
        print("  effect NAME [S]  - Trigger effect with optional speed (1-10)")
        print("  white [I]        - Full white with optional intensity")
        print("  off              - Turn off")
        print("  status           - Show current status")
        print("  help             - Show this help")
        print("  quit             - Exit interactive mode")
        print()
        
        while True:
            try:
                command = input("GVM> ").strip().lower()
                
                if not command:
                    continue
                    
                parts = command.split()
                cmd = parts[0]
                
                if cmd == "quit" or cmd == "exit":
                    break
                elif cmd == "help":
                    continue  # Help already shown above
                elif cmd == "rgb":
                    if len(parts) >= 4:
                        r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
                        i = int(parts[4]) if len(parts) > 4 else None
                        self.gvm.set_rgb_color(r, g, b, i)
                        print(f"Set RGB({r}, {g}, {b})" + (f" @ {i}%" if i else ""))
                    else:
                        print("Usage: rgb R G B [intensity]")
                elif cmd == "hsi":
                    if len(parts) >= 4:
                        h, s, i = float(parts[1]), float(parts[2]), float(parts[3])
                        self.gvm.set_hsi_color(h, s, i)
                        print(f"Set HSI({h}, {s}, {i})")
                    else:
                        print("Usage: hsi H S I")
                elif cmd == "cct":
                    if len(parts) >= 2:
                        cct = int(parts[1])
                        gm = int(parts[2]) if len(parts) > 2 else 0
                        i = float(parts[3]) if len(parts) > 3 else None
                        self.gvm.set_cct_color(cct, gm, i)
                        print(f"Set CCT({cct}K, GM:{gm})" + (f" @ {i}%" if i else ""))
                    else:
                        print("Usage: cct temperature [gm] [intensity]")
                elif cmd == "intensity":
                    if len(parts) >= 2:
                        intensity = float(parts[1])
                        self.gvm.set_master_intensity(intensity)
                        print(f"Set intensity to {intensity}%")
                    else:
                        print("Usage: intensity VALUE")
                elif cmd == "mode":
                    if len(parts) >= 2:
                        mode_name = parts[1]
                        mode_map = {
                            'rgb': GVMMode.RGB_33,
                            'hsi': GVMMode.HSI_33,
                            'cct': GVMMode.CCT_33,
                            'cct_rgb': GVMMode.CCT_RGB_33,
                            'cct_hsi': GVMMode.CCT_HSI_33,
                            'effect': GVMMode.EFFECT,
                            'pixelfx': GVMMode.PIXEL_FX
                        }
                        if mode_name in mode_map:
                            self.gvm.set_mode(mode_map[mode_name])
                            print(f"Set mode to {mode_name}")
                        else:
                            print(f"Unknown mode: {mode_name}")
                            print(f"Available modes: {', '.join(mode_map.keys())}")
                    else:
                        print("Usage: mode MODE")
                elif cmd == "effect":
                    if len(parts) >= 2:
                        effect_name = parts[1]
                        speed = int(parts[2]) if len(parts) > 2 else 5
                        effect_map = {
                            'lightning': GVMEffectType.LIGHTNING,
                            'candle': GVMEffectType.CANDLE,
                            'tv': GVMEffectType.TV,
                            'strobe': GVMEffectType.PAPARAZZI,
                            'explosion': GVMEffectType.EXPLOSION,
                            'pulsing': GVMEffectType.PULSING,
                            'disco': GVMEffectType.DISCO
                        }
                        if effect_name in effect_map:
                            self.gvm.set_effect(effect_map[effect_name], speed)
                            print(f"Triggered {effect_name} effect @ speed {speed}")
                        else:
                            print(f"Unknown effect: {effect_name}")
                            print(f"Available effects: {', '.join(effect_map.keys())}")
                    else:
                        print("Usage: effect NAME [speed]")
                elif cmd == "white":
                    intensity = float(parts[1]) if len(parts) > 1 else 100
                    self.gvm.full_white(intensity)
                    print(f"Set to white @ {intensity}%")
                elif cmd == "off":
                    self.gvm.off()
                    print("Light turned off")
                elif cmd == "status":
                    print(f"Mode: {self.gvm.current_mode.description}")
                    print(f"Intensity: {self.gvm.master_intensity}%")
                    print(f"RGB: {self.gvm.rgb_color.to_tuple()}")
                    print(f"Connected: {self.dmx.is_connected}")
                    print(f"Transmitting: {self.dmx.is_transmitting}")
                else:
                    print(f"Unknown command: {cmd}")
                    
            except KeyboardInterrupt:
                print("\nExiting interactive mode...")
                break
            except Exception as e:
                print(f"Error: {e}")
        
        print("Interactive mode ended")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description="DMX and GVM Light Testing CLI")
    parser.add_argument("--port", "-p", help="DMX serial port (auto-detect if not specified)")
    parser.add_argument("--channel", "-c", type=int, default=1, help="Starting DMX channel (default: 1)")
    parser.add_argument("--list-ports", "-l", action="store_true", help="List available serial ports")
    parser.add_argument("--test", "-t", choices=["dmx", "gvm", "effects", "demo", "liftingcast"], 
                       help="Run specific test")
    parser.add_argument("--interactive", "-i", action="store_true", help="Start interactive mode")
    parser.add_argument("--no-transmission", action="store_true", help="Don't start automatic transmission")
    
    args = parser.parse_args()
    
    # List ports if requested
    if args.list_ports:
        import serial.tools.list_ports
        print("Available serial ports:")
        for port in serial.tools.list_ports.comports():
            print(f"  {port.device} - {port.description}")
        return
    
    # Initialize CLI
    cli = DMXTestCLI(port=args.port, start_channel=args.channel)
    
    try:
        # Connect to DMX interface
        if not cli.connect():
            return 1
        
        # Start transmission unless disabled
        if not args.no_transmission:
            cli.start_transmission()
        
        # Run specific test
        if args.test:
            if args.test == "dmx":
                cli.test_basic_dmx()
            elif args.test == "gvm":
                cli.test_gvm_modes()
            elif args.test == "effects":
                cli.test_effects()
            elif args.test == "demo":
                cli.color_demo()
            elif args.test == "liftingcast":
                cli.simulate_liftingcast_signals()
        
        # Interactive mode
        if args.interactive or not args.test:
            cli.interactive_mode()
    
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        cli.stop_transmission()
        cli.disconnect()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())