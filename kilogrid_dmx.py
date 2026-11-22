#!/usr/bin/env python3
"""
KiloGrid DMX

Stage lighting driven by a KiloGrid hub's live meet feed (the desktop app's local server),
over an Enttec Open DMX USB on this machine. Each fixture belongs to one platform, so one
Enttec can light every platform of the meet.

It follows the same rules as KiloGrid's built-in lights engine (apps/hub/src/lights/engine.ts),
per platform:
  - all three referee lights in: that platform's fixtures go to the good-lift colour (2+ good)
    or the no-lift colour (2+ bad)
  - lights cleared or partial: back to the theme colour
  - attempt clock started (not a break clock): that platform's staging fixtures flash on
  - the first meet frame after connecting is a baseline and never fires a scene

READ-ONLY: it subscribes the way an OBS overlay page does and refuses to send anything else,
so it cannot start a clock, record a decision or change the meet.

    python kilogrid_dmx.py                    # uses kilogrid.conf
    python kilogrid_dmx.py my.conf
    python kilogrid_dmx.py --dry-run          # no DMX hardware: log what the lights would do
    python kilogrid_dmx.py --test             # cycle every fixture through every scene
"""

import argparse
import json
import logging
import re
import signal
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import websocket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kilogrid_dmx")

# The only messages this client may send. All are in the hub's public read tier.
ALLOWED_OUTBOUND = frozenset({"RESOLVE_MEET", "SUBSCRIBE_MEET"})
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
DECIDED = ("good", "bad")
FIXTURE_TYPES = ("gvm", "washer")
ROLES = ("platform", "staging")
FIXTURE_CHANNELS = {"gvm": 4, "washer": 9}


class ForbiddenMessage(PermissionError):
    pass


@dataclass
class FixtureSpec:
    kind: str       # gvm | washer
    address: int    # DMX start channel, 1-512
    role: str       # platform | staging
    platform: str   # platform number or name, as in the meet


def load_config(filename: str) -> Tuple[Dict[str, str], List[str]]:
    """key=value settings, plus every `fixture=` line in order (the key may repeat)."""
    config: Dict[str, str] = {}
    fixtures: List[str] = []
    try:
        with open(filename, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = (s.strip() for s in line.split("=", 1))
                if key == "fixture":
                    fixtures.append(value)
                else:
                    config[key] = value
    except OSError as e:
        raise SystemExit(
            f"Could not read config file '{filename}' ({e}). "
            "Copy kilogrid.conf.example to kilogrid.conf and fill in the hub and meet."
        )
    for key in ("hub", "meet"):
        if not config.get(key):
            raise SystemExit(f"'{key}' is missing from {filename}.")
    return config, fixtures


def parse_fixtures(config: Dict[str, str], lines: List[str]) -> List[FixtureSpec]:
    """`fixture=<type> <address> <platform|staging> <platform>` lines, or the older
    single-platform keys (platform=, platform_fixture_type=, ...) when there are none."""
    specs: List[FixtureSpec] = []
    if lines:
        for line in lines:
            parts = line.replace(",", " ").split()
            if len(parts) != 4:
                raise SystemExit(f"fixture={line}: expected 'type address role platform', e.g. fixture=washer 1 platform 1")
            kind, address, role, platform = parts
            kind, role = kind.lower(), role.lower()
            if kind not in FIXTURE_TYPES:
                raise SystemExit(f"fixture={line}: type must be one of {', '.join(FIXTURE_TYPES)}")
            if role not in ROLES:
                raise SystemExit(f"fixture={line}: role must be platform or staging")
            if not address.isdigit() or not 1 <= int(address) <= 512 - FIXTURE_CHANNELS[kind] + 1:
                raise SystemExit(f"fixture={line}: address must be 1-{512 - FIXTURE_CHANNELS[kind] + 1} for a {kind}")
            specs.append(FixtureSpec(kind, int(address), role, platform))
    else:
        platform = str(config.get("platform", "1"))
        for role, default_kind, default_ch in (("platform", "gvm", 1), ("staging", "none", 10)):
            kind = config.get(f"{role}_fixture_type", default_kind).lower()
            if kind == "none":
                continue
            if kind not in FIXTURE_TYPES:
                raise SystemExit(f"{role}_fixture_type={kind}: use gvm, washer or none")
            address = number(config, f"{role}_dmx_start_channel", default_ch, 1, 512 - FIXTURE_CHANNELS[kind] + 1)
            specs.append(FixtureSpec(kind, address, role, platform))
    if not specs:
        raise SystemExit("No fixtures configured: add fixture= lines (see kilogrid.conf.example).")
    # One address does one job: a repeated identical line is harmless and dropped, but the
    # same address with another type, role or platform, or overlapping channel ranges,
    # is a typo that would leave lights doing nothing, so it is refused.
    unique: List[FixtureSpec] = []
    for spec in specs:
        if spec in unique:
            continue
        for other in unique:
            a_end = spec.address + FIXTURE_CHANNELS[spec.kind] - 1
            b_end = other.address + FIXTURE_CHANNELS[other.kind] - 1
            if spec.address == other.address:
                raise SystemExit(
                    f"DMX address {spec.address} is on two different fixture lines "
                    f"({other.kind} {other.role} {other.platform} and {spec.kind} {spec.role} {spec.platform}). "
                    "One address can only do one job.")
            if spec.address <= b_end and other.address <= a_end:
                raise SystemExit(f"Fixtures at {other.address} ({other.kind}) and {spec.address} ({spec.kind}) share DMX channels.")
        unique.append(spec)
    return unique


def number(config: Dict[str, str], key: str, default, lo, hi, kind=int):
    """A numeric setting within [lo, hi], or a plain error naming the key."""
    raw = config.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise SystemExit(f"{key}={raw}: must be a number.")
    if not lo <= value <= hi:
        raise SystemExit(f"{key}={raw}: must be between {lo:g} and {hi:g}.")
    return value


def hub_url(hub: str) -> str:
    """'192.168.8.201', '192.168.8.201:5503' or a full ws:// URL."""
    if hub.startswith(("ws://", "wss://")):
        return hub
    return f"ws://{hub}" if ":" in hub else f"ws://{hub}:5503"


def lights_result(ref_lights) -> Optional[str]:
    """'good' / 'bad' once all three refs are in, else None (the engine's rule)."""
    if not isinstance(ref_lights, dict):
        return None
    decisions = [(ref_lights.get(pos) or {}).get("decision") for pos in ("left", "head", "right")]
    if not all(d in DECIDED for d in decisions):
        return None
    return "good" if decisions.count("good") >= 2 else "bad"


class Color:
    def __init__(self, config: Dict[str, str], prefix: str, default=(255, 255, 255, 100)):
        r, g, b, i = default
        self.r = number(config, f"{prefix}_r", r, 0, 255)
        self.g = number(config, f"{prefix}_g", g, 0, 255)
        self.b = number(config, f"{prefix}_b", b, 0, 255)
        self.intensity = number(config, f"{prefix}_intensity", i, 0, 100)

    def values(self):
        return self.r, self.g, self.b, self.intensity

    def __repr__(self):
        return f"RGB({self.r},{self.g},{self.b}) @ {self.intensity}%"


OFF = (0, 0, 0, 0)
SCENE_LABEL = {"theme": "Theme", "good": "GOOD LIFT", "bad": "NO LIFT"}


class Lights:
    """Every fixture, grouped by platform. With dry_run there is no DMX: changes are only logged."""

    def __init__(self, config: Dict[str, str], specs: List[FixtureSpec], dry_run: bool):
        self.config = config
        self.specs = specs
        self.dry_run = dry_run
        self.dmx = None
        self.fixtures: List[Tuple[FixtureSpec, object]] = []
        self.platforms = list(dict.fromkeys(s.platform for s in specs))  # in config order
        self.colors = {
            "theme": Color(config, "theme", (255, 255, 255, 25)),
            "good": Color(config, "success", (255, 255, 255, 100)),
            "bad": Color(config, "failure", (255, 0, 0, 100)),
        }
        self.staging_seconds = number(config, "staging_flash_seconds", 3.0, 0.1, 600, float)
        self.staging_on_clock = config.get("staging_on_clock_start", "true").lower() in ("1", "true", "yes", "on")
        self.scene: Dict[str, Optional[str]] = {p: None for p in self.platforms}
        self._staging_timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _fixture(self, spec: FixtureSpec):
        from gvm_light_controller import GVMLightController, GVMMode
        from washer_light_controller import WasherLightController

        if spec.kind == "gvm":
            light = GVMLightController(self.dmx, spec.address)
            light.set_mode(GVMMode.RGB_33)
            return light
        return WasherLightController(self.dmx, spec.address)

    def open(self):
        if self.dry_run:
            logger.info("Dry run: no DMX output")
        else:
            from dmx_controller import DMXError, EnttecOpenDMX

            self.dmx = EnttecOpenDMX(port=self.config.get("dmx_port") or None)
            try:
                connected = self.dmx.connect()
            except DMXError:
                connected = False
            if not connected:
                raise SystemExit("Could not open the Enttec. Check the USB cable and the port (python dmx_test_cli.py --list-ports).")
        for spec in self.specs:
            self.fixtures.append((spec, None if self.dry_run else self._fixture(spec)))
            logger.info(f"Platform {spec.platform}: {spec.role} {spec.kind} at DMX address {spec.address}")
        for p in self.platforms:
            self.set_scene(p, "theme")
            self._staging(p, False)
        if self.dmx:
            self.dmx.set_frame_rate(30)
            self.dmx.start_transmission()

    def close(self):
        for t in self._staging_timers.values():
            t.cancel()
        if self.dmx:
            with self._lock:
                for _, light in self.fixtures:
                    light.set_rgb_color(*OFF)
            time.sleep(0.2)  # let a blackout frame go out
            self.dmx.disconnect()

    def _set(self, platform: str, role: str, values):
        for spec, light in self.fixtures:
            if light is not None and spec.platform == platform and spec.role == role:
                light.set_rgb_color(*values)

    def set_scene(self, platform: str, scene: str):
        color = self.colors[scene]
        with self._lock:
            if self.scene.get(platform) == scene:
                return
            self.scene[platform] = scene
            self._set(platform, "platform", color.values())
        logger.info(f"Platform {platform} lights: {SCENE_LABEL[scene]} {color}")

    def _staging(self, platform: str, on: bool):
        with self._lock:
            self._set(platform, "staging", self.colors["theme"].values() if on else OFF)

    def flash_staging(self, platform: str):
        if not self.staging_on_clock:
            return
        def off():
            # A timer that already started can't be cancelled, so each one checks it is
            # still the newest flash before turning staging off.
            with self._lock:
                if self._staging_timers.get(platform) is not timer:
                    return
                del self._staging_timers[platform]
                self._set(platform, "staging", OFF)
            logger.info(f"Platform {platform} staging off")

        timer = threading.Timer(self.staging_seconds, off)
        timer.daemon = True
        with self._lock:
            old = self._staging_timers.get(platform)
            self._staging_timers[platform] = timer
            self._set(platform, "staging", self.colors["theme"].values())
        if old:
            old.cancel()
        logger.info(f"Platform {platform} staging on for {self.staging_seconds:g}s (clock started)")
        timer.start()


class KiloGridFeed:
    """Read-only meet feed from the hub; reconnects on its own."""

    def __init__(self, config: Dict[str, str], lights: Lights):
        self.url = hub_url(config["hub"])
        self.meet_ref = config["meet"]
        self.meet_id = self.meet_ref if UUID_RE.match(self.meet_ref) else None
        self.lights = lights
        self.running = False
        self.ws: Optional[websocket.WebSocketApp] = None
        self._baseline: Dict[str, Dict[str, str]] = {}  # platform -> last lights/clock signature
        self._missing_logged = set()

    def _send(self, ws, msg: dict):
        if msg.get("type") not in ALLOWED_OUTBOUND:
            raise ForbiddenMessage(f"refusing to send {msg.get('type')!r}: the meet feed is read-only")
        ws.send(json.dumps(msg))

    def _subscribe(self, ws):
        self._send(ws, {"type": "SUBSCRIBE_MEET", "payload": {"meetId": self.meet_id, "output": "overlay", "wantsPatches": False}})

    def on_open(self, ws):
        logger.info(f"Connected to KiloGrid at {self.url}")
        self._baseline = {}
        if self.meet_id:
            self._subscribe(ws)
        else:
            self._send(ws, {"type": "RESOLVE_MEET", "payload": {"ref": self.meet_ref, "reqId": "kilogrid-dmx"}})

    def on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        kind = msg.get("type")
        payload = msg.get("payload") or {}
        if kind == "RESOLVE_MEET_RESULT":
            if payload.get("ok") and payload.get("id"):
                self.meet_id = payload["id"]
                logger.info(f"Meet '{self.meet_ref}' is {self.meet_id}")
                self._subscribe(ws)
            else:
                logger.error(f"KiloGrid has no meet '{self.meet_ref}'. Check 'meet' in the config (the slug from the meet's URL, or its id). Retrying.")
                ws.close()
        elif kind == "SUBSCRIBE_MEET_RESULT":
            if payload.get("ok"):
                logger.info("Subscribed to the meet feed")
            else:
                logger.error(f"KiloGrid refused the subscription: {payload.get('error') or payload}. Retrying.")
                ws.close()
        elif kind == "MEET_DATA_UPDATE":
            data = payload.get("data") or {}
            if "platforms" not in data and isinstance(data.get("meet"), dict):
                data = data["meet"]
            self.apply(data)

    def find_platform(self, platforms: dict, wanted: str) -> Optional[dict]:
        if wanted in platforms:
            return platforms[wanted]
        for p in platforms.values():  # by name as a fallback ("Platform A")
            if isinstance(p, dict) and str(p.get("name", "")).strip().lower() == wanted.lower():
                return p
        if wanted not in self._missing_logged:
            names = ", ".join(f"{k} ({(v or {}).get('name')})" for k, v in platforms.items())
            logger.error(f"No platform '{wanted}' in this meet. Platforms: {names or 'none'}")
            self._missing_logged.add(wanted)
        return None

    def apply(self, data: dict):
        """One meet frame: the engine's per-platform diff, for each platform with fixtures."""
        platforms = data.get("platforms")
        if not isinstance(platforms, dict):
            return
        for wanted in self.lights.platforms:
            p = self.find_platform(platforms, wanted)
            if isinstance(p, dict):
                self._apply_platform(wanted, p)

    def _apply_platform(self, key: str, p: dict):
        ref_lights = p.get("refLights")
        result = lights_result(ref_lights)
        lights_sig = "none" if not ref_lights else f"{result or 'partial'}:{json.dumps(ref_lights, sort_keys=True)}"
        clock = p.get("clockState") or "initial"
        prev = self._baseline.get(key)
        self._baseline[key] = {"lights": lights_sig, "clock": clock}
        if prev is None:
            logger.info(f"Platform {key} '{p.get('name')}': clock {clock}, lights {result or ('partial' if ref_lights else 'none')} (baseline, no change)")
            return
        if prev["lights"] != lights_sig:
            self.lights.set_scene(key, result or "theme")
        if prev["clock"] != "started" and clock == "started" and p.get("clockKind") != "break":
            self.lights.flash_staging(key)

    def on_error(self, _ws, error):
        logger.warning(f"KiloGrid connection error: {error}")

    def on_close(self, _ws, _code, _msg):
        logger.warning("Disconnected from KiloGrid; platform lights back to theme")
        for p in self.lights.platforms:
            self.lights.set_scene(p, "theme")

    def run(self):
        self.running = True
        backoff = 1.0
        while self.running:
            started = time.time()
            self.ws = websocket.WebSocketApp(
                self.url, on_open=self.on_open, on_message=self.on_message,
                on_error=self.on_error, on_close=self.on_close,
            )
            # Pings catch a hub that vanished without closing the socket (network drop).
            self.ws.run_forever(ping_interval=10, ping_timeout=5)
            if not self.running:
                break
            backoff = 1.0 if time.time() - started > 30 else min(backoff * 2, 15.0)
            logger.info(f"Reconnecting in {backoff:g}s")
            time.sleep(backoff)

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()


def run_test(lights: Lights):
    """Each platform in turn: good, theme, no lift, theme, staging flash."""
    try:
        for p in lights.platforms:
            for step in ("good", "theme", "bad", "theme"):
                time.sleep(3)
                lights.set_scene(p, step)
            time.sleep(3)
            lights.flash_staging(p)
            time.sleep(lights.staging_seconds + 1)
    except KeyboardInterrupt:
        logger.info("Test stopped")
    finally:
        lights.close()


def main():
    ap = argparse.ArgumentParser(description="DMX stage lighting from a KiloGrid meet feed")
    ap.add_argument("config", nargs="?", default="kilogrid.conf")
    ap.add_argument("--dry-run", action="store_true", help="no DMX hardware: log scene changes only")
    ap.add_argument("--test", action="store_true", help="cycle each platform's fixtures through every scene, then exit")
    args = ap.parse_args()

    config, fixture_lines = load_config(args.config)
    lights = Lights(config, parse_fixtures(config, fixture_lines), dry_run=args.dry_run)
    lights.open()
    if args.test:
        run_test(lights)
        return

    feed = KiloGridFeed(config, lights)
    logger.info(f"KiloGrid DMX: hub {feed.url}, meet {feed.meet_ref}, platforms {', '.join(lights.platforms)}. Ctrl+C to stop.")

    # The feed runs on its own thread so Ctrl+C and systemd's SIGTERM only set a flag here;
    # closing the socket from inside a signal handler can deadlock run_forever.
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    thread = threading.Thread(target=feed.run, name="kilogrid-feed", daemon=True)
    thread.start()
    try:
        while not stop.wait(1.0) and thread.is_alive():
            pass
        logger.info("Stopping")
    finally:
        feed.stop()
        lights.close()
        logger.info("Stopped")


if __name__ == "__main__":
    main()
