# LiftingCast DMX

Turns [LiftingCast](https://liftingcast.com) referee decisions into stage lighting. It listens to the LiftingCast websocket relay and drives DMX fixtures over an Enttec Open DMX USB interface: green on a good lift, red on a no lift, back to your theme color after a few seconds. It can also run a second fixture over the staging area tied to the platform clock.

Built for powerlifting livestream production, where the lighting should react to the meet without anyone touching a board.

## Hardware

- Enttec Open DMX USB (or any FTDI-based open DMX interface)
- One or two DMX fixtures. Two profiles are included: GVM PRO-BD45R stick lights (4ch RGB mode) and generic 9-channel RGBA washers. Other fixtures are easy to add.

## Setup

```bash
pip install -r requirements.txt
cp liftingcast.conf.example liftingcast.conf
```

Edit `liftingcast.conf` with your meet ID, password, platform ID, and the relay IP, then set your fixture types and DMX addresses. Run it with:

```bash
python liftingcast_dmx.py
```

## KiloGrid

`kilogrid_dmx.py` drives the same fixtures from a KiloGrid hub (the desktop app's local server,
port 5503) instead of the LiftingCast relay. It follows KiloGrid's built-in lights engine: all three
refs in → good-lift or no-lift colour, lights cleared → theme, attempt clock started → staging flash.
It only subscribes to the meet feed, the way an OBS overlay does, and cannot change anything.

```bash
cp kilogrid.conf.example kilogrid.conf   # set hub, meet (slug or id), platform, fixtures
python kilogrid_dmx.py --dry-run         # check the feed without the Enttec
python kilogrid_dmx.py
```

On a Linux box, `./install-linux.sh` makes a venv, gives you serial port access and installs a
`kilogrid-dmx` systemd service (`sudo systemctl enable --now kilogrid-dmx`,
`journalctl -u kilogrid-dmx -f`).

## Testing without a meet

`dmx_test_cli.py` exercises the DMX interface and fixtures directly:

```bash
python dmx_test_cli.py --list-ports   # find your Enttec
python dmx_test_cli.py --test dmx     # basic output test
python dmx_test_cli.py --interactive  # manual color/effect control
```

## Files

- `kilogrid_dmx.py` - KiloGrid hub feed and light logic (`--test` cycles the fixtures through every scene)
- `liftingcast_dmx.py` - LiftingCast relay feed and light logic
- `dmx_controller.py` - DMX512 output over the Enttec Open DMX USB
- `gvm_light_controller.py` / `washer_light_controller.py` - fixture profiles
- `dmx_test_cli.py` - hardware test tool
