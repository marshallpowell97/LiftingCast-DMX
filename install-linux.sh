#!/usr/bin/env bash
# Set up KiloGrid DMX on a Linux box with the Enttec plugged in.
# Run from the repo folder as the user who will run it (not root):  ./install-linux.sh
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

command -v python3 >/dev/null || { echo "python3 is not installed (sudo apt install python3 python3-venv)"; exit 1; }
python3 -m venv venv || { echo "Could not make a venv: sudo apt install python3-venv"; exit 1; }
venv/bin/pip install -q -r requirements.txt

[ -f kilogrid.conf ] || { cp kilogrid.conf.example kilogrid.conf; echo "Made kilogrid.conf from the example: check hub, meet and platform."; }

# The Enttec shows up as /dev/ttyUSB*, owned by the dialout group.
if ! id -nG "$USER" | grep -qw dialout; then
  sudo usermod -aG dialout "$USER"
  echo "Added $USER to dialout (serial port access). Log out and back in before running by hand."
fi

sudo tee /etc/systemd/system/kilogrid-dmx.service >/dev/null <<EOF
[Unit]
Description=KiloGrid DMX lights
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
SupplementaryGroups=dialout
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python $DIR/kilogrid_dmx.py $DIR/kilogrid.conf
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
echo
echo "Installed. Start it and follow the log:"
echo "  sudo systemctl enable --now kilogrid-dmx"
echo "  journalctl -u kilogrid-dmx -f"
