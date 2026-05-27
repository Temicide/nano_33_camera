#!/usr/bin/env bash
set -euo pipefail

echo "Starting Edge Impulse daemon..."
echo "Follow the prompts to:"
echo "  1. Log in to your Edge Impulse account"
echo "  2. Select your project"
echo "  3. Connect the Arduino Nano 33 BLE Sense"
echo ""
echo "Once connected, go to Edge Impulse Studio → Data Acquisition"
echo "to capture images of your blister pack squares."
echo ""

edge-impulse-daemon --clean
