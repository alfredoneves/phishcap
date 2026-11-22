#!/bin/bash

if [ "$EUID" -ne 0 ]; then
    echo "Run this script as root."
    exit 1
fi

set -e

echo "[+] Updating package lists..."
apt-get update

echo "[+] Installing system dependencies..."
apt-get install -y \
    hostapd \
    dnsmasq \
    nftables \
    python3

echo "[+] Dependencies installed successfully."
