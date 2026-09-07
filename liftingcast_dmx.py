#!/usr/bin/env python3
"""
LiftingCast DMX Integration
Simple single-file integration between LiftingCast relay station and DMX lighting
"""

import websocket
import json
import base64
import threading
import time
import logging
from typing import Dict, Any, Optional
from dmx_controller import EnttecOpenDMX
from washer_light_controller import WasherLightController
from gvm_light_controller import GVMLightController, GVMMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LiftingCastDMX:
    def __init__(self, config_file: str = "liftingcast.conf"):
        self.config = self.load_config(config_file)
        self.ws = None
        self.dmx = None
        self.platform_light = None  # Platform lights (referee decisions)
        self.staging_light = None   # Staging lights (timer activation)
        self.current_light_state = 'theme'  # track current light state
        self.staging_timer = None
        self.current_clock_state = None
        self.running = False

    def load_config(self, filename: str) -> Dict[str, str]:
        """Load simple key=value config file"""
        config = {}
        try:
            with open(filename, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
            logger.info(f"Loaded config from {filename}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise SystemExit(
                f"Could not read config file '{filename}'. "
                "Copy liftingcast.conf.example to liftingcast.conf and fill in your meet details."
            )
        return config

    def setup_dmx(self):
        """Initialize DMX controller and light"""
        try:
            self.dmx = EnttecOpenDMX()
            if not self.dmx.connect():
                raise Exception("Failed to connect to DMX interface")

            # Setup fixtures based on type
            platform_channel = int(self.config['platform_dmx_start_channel'])
            staging_channel = int(self.config['staging_dmx_start_channel'])

            platform_type = self.config.get('platform_fixture_type', 'washer').lower()
            staging_type = self.config.get('staging_fixture_type', 'washer').lower()

            # Create platform fixture
            if platform_type == 'gvm':
                self.platform_light = GVMLightController(self.dmx, platform_channel)
                self.platform_light.set_mode(GVMMode.RGB_33)
                logger.info(f"Platform: GVM light on channel {platform_channel}")
            else:  # washer
                self.platform_light = WasherLightController(self.dmx, platform_channel)
                logger.info(f"Platform: Washer light on channel {platform_channel}")

            # Create staging fixture
            if staging_type == 'gvm':
                self.staging_light = GVMLightController(self.dmx, staging_channel)
                self.staging_light.set_mode(GVMMode.RGB_33)
                logger.info(f"Staging: GVM light on channel {staging_channel}")
            else:  # washer
                self.staging_light = WasherLightController(self.dmx, staging_channel)
                logger.info(f"Staging: Washer light on channel {staging_channel}")

            # Set initial colors
            self.set_theme_color_static()
            self.current_light_state = 'theme'

            # Initialize staging lights to OFF
            self.set_staging_lights_off()

            # Start continuous DMX transmission (required for fixtures to stay on)
            self.dmx.set_frame_rate(30)  # 30 FPS
            self.dmx.start_transmission()
            logger.info("DMX system initialized - continuous transmission at 30 FPS")

        except Exception as e:
            logger.error(f"DMX setup failed: {e}")
            return False
        return True

    def set_theme_color_static(self):
        """Set the default theme color"""
        try:
            r = int(self.config['theme_r'])
            g = int(self.config['theme_g'])
            b = int(self.config['theme_b'])
            intensity = int(self.config['theme_intensity'])
            if self.platform_light:
                self.platform_light.set_rgb_color(r, g, b, intensity)
                logger.info(f"Theme color set: RGB({r},{g},{b}) @ {intensity}%")
        except Exception as e:
            logger.error(f"Failed to set theme color: {e}")

    def set_theme_color(self):
        """Set the default theme color"""
        if self.current_light_state == 'theme':
            return  # Already theme color

        r = int(self.config['theme_r'])
        g = int(self.config['theme_g'])
        b = int(self.config['theme_b'])
        intensity = int(self.config['theme_intensity'])
        if self.platform_light:
            self.platform_light.set_rgb_color(r, g, b, intensity)
            self.current_light_state = 'theme'
            logger.info("Theme color restored")

    def set_staging_lights_on(self):
        """Turn on staging lights with theme color"""
        r = int(self.config['theme_r'])
        g = int(self.config['theme_g'])
        b = int(self.config['theme_b'])
        intensity = int(self.config['theme_intensity'])

        if self.staging_light:
            self.staging_light.set_rgb_color(r, g, b, intensity)
            logger.info("Staging lights ON - Timer started")

    def set_staging_lights_off(self):
        """Turn off staging lights"""
        if self.staging_light:
            self.staging_light.set_rgb_color(0, 0, 0, 0)  # All off
            logger.info("Staging lights OFF")

    def handle_timer_start(self):
        """Handle timer start - turn on staging lights for 3 seconds"""
        if self.staging_timer:
            self.staging_timer.cancel()

        # Turn on staging lights
        self.set_staging_lights_on()

        # Set timer to turn off after 3 seconds
        self.staging_timer = threading.Timer(3.0, self.set_staging_lights_off)
        self.staging_timer.start()

    def set_success_color(self):
        """Set green success lighting"""
        if self.current_light_state == 'success':
            return  # Already green

        r = int(self.config['success_r'])
        g = int(self.config['success_g'])
        b = int(self.config['success_b'])
        intensity = int(self.config['success_intensity'])

        self.platform_light.set_rgb_color(r, g, b, intensity)
        self.current_light_state = 'success'
        logger.info("GOOD LIFT - Green lights activated")

    def set_failure_color(self):
        """Set red failure lighting"""
        if self.current_light_state == 'failure':
            return  # Already red

        r = int(self.config['failure_r'])
        g = int(self.config['failure_g'])
        b = int(self.config['failure_b'])
        intensity = int(self.config['failure_intensity'])

        self.platform_light.set_rgb_color(r, g, b, intensity)
        self.current_light_state = 'failure'
        logger.info("BAD LIFT - Red lights activated")

    def calculate_lift_result(self, ref_lights: Dict) -> Optional[str]:
        """Calculate lift result - need all 3 refs to decide, then 2 out of 3 wins"""
        decisions = []
        for position in ['left', 'head', 'right']:
            decision = ref_lights.get(position, {}).get('decision')
            if decision in ['good', 'bad']:
                decisions.append(decision)

        # Must have all 3 decisions before showing any result
        if len(decisions) < 3:
            return None

        good_count = decisions.count('good')
        bad_count = decisions.count('bad')

        if good_count >= 2:
            return 'good'
        elif bad_count >= 2:
            return 'bad'
        else:
            return None

    def get_current_lifter(self, data: Dict) -> Optional[str]:
        """Get current lifter ID from platform data"""
        platform_id = self.config['platform_id']
        platform = data.get('platforms', {}).get(platform_id)
        if platform and platform.get('currentAttempt'):
            return platform['currentAttempt'].get('lifter', {}).get('id')
        return None

    def on_message(self, ws, message):
        """Handle WebSocket messages"""
        try:
            if message == "pong":
                return

            # Log all WebSocket messages to file for debugging
            with open("websocket_debug.log", "a") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

            data = json.loads(message)

            # Get referee decisions for current platform
            platform_id = self.config['platform_id']
            platform = data.get('platforms', {}).get(platform_id)
            if not platform:
                return

            # Monitor clock state for staging lights
            clock_state = platform.get('clockState')
            clock_timer_length = platform.get('clockTimerLength')

            # Always log the current clock state for debugging
            logger.info(f"Platform {platform_id}: clockState='{clock_state}', clockTimerLength={clock_timer_length}")

            if clock_state != self.current_clock_state:
                logger.info(f"CLOCK STATE CHANGE: {self.current_clock_state} -> {clock_state}")
                self.current_clock_state = clock_state
                if clock_state == 'started':
                    logger.info("TIMER STARTED - activating staging lights")
                    self.handle_timer_start()
                elif clock_state == 'stopped':
                    logger.info("TIMER STOPPED")
                elif clock_state == 'initial':
                    logger.info("TIMER RESET TO INITIAL")

            # Handle referee decisions for platform lights
            ref_lights = platform.get('refLights', {})
            lift_result = self.calculate_lift_result(ref_lights)

            # Set lights based on current referee decisions
            if lift_result == 'good':
                self.set_success_color()
            elif lift_result == 'bad':
                self.set_failure_color()
            else:
                # Less than 2 decisions of any type - back to theme
                self.set_theme_color()

        except json.JSONDecodeError:
            logger.warning(f"Could not parse message: {message}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def on_error(self, _, error):
        """Handle WebSocket errors"""
        logger.error(f"WebSocket error: {error}")

    def on_close(self, _, _close_status_code, _close_msg):
        """Handle WebSocket close"""
        logger.warning("WebSocket connection closed")
        if self.running:
            logger.info("Attempting to reconnect in 5 seconds...")
            time.sleep(5)
            self.connect_websocket()

    def on_open(self, _):
        """Handle WebSocket open"""
        logger.info("Connected to LiftingCast relay station")
        self.send_ping()

    def send_ping(self):
        """Send periodic ping to keep connection alive"""
        def ping_loop():
            while self.running and self.ws:
                try:
                    if self.ws.sock and self.ws.sock.connected:
                        self.ws.send("ping")
                        logger.debug("Sent ping")
                    time.sleep(30)
                except Exception as e:
                    logger.error(f"Ping failed: {e}")
                    break

        ping_thread = threading.Thread(target=ping_loop, daemon=True)
        ping_thread.start()

    def connect_websocket(self):
        """Connect to LiftingCast WebSocket"""
        # Build auth token
        meet_id = self.config['meet_id']
        password = self.config['password']
        auth_token = base64.b64encode(f"{meet_id}:{password}".encode()).decode()

        # Build WebSocket URL
        relay_ip = self.config['relay_ip']
        url = f"ws://{relay_ip}/websocket?meetId={meet_id}&auth={auth_token}"

        logger.info(f"Connecting to {relay_ip}...")

        self.ws = websocket.WebSocketApp(
            url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )

        # Run WebSocket in background thread
        ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        ws_thread.start()

    def start(self):
        """Start the LiftingCast DMX system"""
        logger.info("Starting LiftingCast DMX Integration")

        # Setup DMX
        if not self.setup_dmx():
            logger.error("DMX setup failed - exiting")
            return

        logger.info("DMX lights should now be on with theme color")

        # Connect WebSocket
        self.running = True
        self.connect_websocket()

        try:
            # Keep main thread alive - DMX transmission running in background
            logger.info("System running - continuous DMX transmission active")
            while self.running:
                time.sleep(1)  # Just keep alive for WebSocket
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.stop()

    def stop(self):
        """Stop the system"""
        self.running = False

        if self.staging_timer:
            self.staging_timer.cancel()

        if self.ws:
            self.ws.close()

        if self.dmx:
            self.dmx.disconnect()

        logger.info("System stopped")


if __name__ == "__main__":
    import sys

    config_file = "liftingcast.conf"
    if len(sys.argv) > 1:
        config_file = sys.argv[1]

    print("LiftingCast DMX Integration")
    print("===========================")
    print(f"Config file: {config_file}")
    print("Press Ctrl+C to stop")
    print()

    system = LiftingCastDMX(config_file)
    system.start()