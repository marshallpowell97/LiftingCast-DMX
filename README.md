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

## Testing without a meet

`dmx_test_cli.py` exercises the DMX interface and fixtures directly:

```bash
python dmx_test_cli.py --list-ports   # find your Enttec
python dmx_test_cli.py --test dmx     # basic output test
python dmx_test_cli.py --interactive  # manual color/effect control
```

## Files

- `liftingcast_dmx.py` - main service, websocket client and light logic
- `dmx_controller.py` - DMX512 output over the Enttec Open DMX USB
- `gvm_light_controller.py` / `washer_light_controller.py` - fixture profiles
- `dmx_test_cli.py` - hardware test tool
