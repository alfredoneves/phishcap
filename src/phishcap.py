#!/usr/bin/env python3
"""Set up the Phishcap isolated captive-portal lab.

Use only on equipment and wireless spectrum you own or are authorized to test.
This launcher is intended for a contained lab; do not collect real credentials.
"""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    from pyfiglet import figlet_format
except ImportError:
    figlet_format = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOSTAPD_CONFIG = PROJECT_ROOT / "config" / "hostapd.conf"
DNSMASQ_CONFIG = PROJECT_ROOT / "config" / "dnsmasq.conf"
LAB_ADDRESS = "10.42.0.1/24"
NFT_TABLE = "cp_lab"

children = []


def banner():
    if figlet_format:
        print(figlet_format("phishcap"))
    else:
        print("=== PHISHCAP ===")
        print("Install the optional banner dependency with: pip install pyfiglet\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Configure and start the Phishcap captive-portal lab."
    )
    parser.add_argument(
        "-i", "--interface",
        help="Wireless interface to use (default: interface in config/hostapd.conf).",
    )
    parser.add_argument(
        "-s", "--ssid",
        help="Lab access-point SSID (default: SSID in config/hostapd.conf).",
    )
    return parser.parse_args()


def run(command, *, check=True, input_text=None):
    """Run a system command and show a useful error if it fails."""
    try:
        return subprocess.run(
            command,
            check=check,
            text=True,
            input=input_text,
        )
    except FileNotFoundError:
        print(f"[-] Required command not found: {command[0]}", file=sys.stderr)
        raise
    except subprocess.CalledProcessError as exc:
        print(f"[-] Command failed ({exc.returncode}): {' '.join(command)}", file=sys.stderr)
        raise


def read_setting(path, key):
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            return stripped.split("=", 1)[1]
    raise ValueError(f"Could not find '{key}=' in {path}")


def update_setting(path, key, value):
    lines = path.read_text(encoding="utf-8").splitlines()
    replacement = f"{key}={value}"
    found = False
    updated = []

    for line in lines:
        if line.strip().startswith(f"{key}="):
            updated.append(replacement)
            found = True
        else:
            updated.append(line)

    if not found:
        updated.append(replacement)

    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def validate_options(interface, ssid):
    # Linux interface names are at most 15 characters. Restrict characters so
    # the value is safe to insert into the nftables configuration as well.
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", interface):
        raise ValueError("Invalid interface name. Use 1-15 letters, numbers, '.', '_' or '-'.")
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise ValueError("SSID must contain between 1 and 32 UTF-8 bytes.")
    if "\n" in ssid or "\r" in ssid:
        raise ValueError("SSID cannot contain newline characters.")


def start_process(command, name, cwd=None):
    print(f"[+] Starting {name}...")
    process = subprocess.Popen(command, cwd=cwd)
    children.append(process)
    # Give the process a moment to report immediate configuration errors.
    time.sleep(1)
    if process.poll() is not None:
        raise RuntimeError(f"{name} exited immediately (status {process.returncode}).")
    return process


def cleanup(*_):
    print("\n[+] Stopping lab services...")
    for process in reversed(children):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    # Remove only the dedicated table created by this script.
    subprocess.run(
        ["nft", "delete", "table", "ip", NFT_TABLE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    print("[+] Lab processes stopped and temporary NAT table removed.")


def main():
    banner()
    args = parse_args()

    if os.geteuid() != 0:
        print("[-] Run this script as root (for example: sudo python3 src/phishcap.py).", file=sys.stderr)
        return 1

    if not HOSTAPD_CONFIG.is_file() or not DNSMASQ_CONFIG.is_file():
        print("[-] Configuration files not found. Run this script from the project checkout.", file=sys.stderr)
        return 1

    interface = args.interface or read_setting(HOSTAPD_CONFIG, "interface")
    ssid = args.ssid or read_setting(HOSTAPD_CONFIG, "ssid")
    validate_options(interface, ssid)

    # Keep both services bound to the same selected wireless interface.
    update_setting(HOSTAPD_CONFIG, "interface", interface)
    update_setting(HOSTAPD_CONFIG, "ssid", ssid)
    update_setting(DNSMASQ_CONFIG, "interface", interface)

    print(f"[+] Interface: {interface}")
    print(f"[+] SSID: {ssid}")
    print("[!] Use only with your own test devices in an isolated lab.")

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        print("[+] Stopping existing hostapd and dnsmasq services...")
        run(["systemctl", "stop", "hostapd", "dnsmasq"])

        run(["nmcli", "device", "set", interface, "managed", "no"])
        run(["rfkill", "unblock", "wifi"])

        print("[+] Preparing wireless interface...")
        run(["ip", "link", "set", interface, "down"])
        run(["iw", "dev", interface, "set", "type", "managed"])
        run(["ip", "addr", "flush", "dev", interface])
        run(["ip", "link", "set", interface, "up"])

        # Use the repository config, rather than a stale /tmp copy.
        start_process(["hostapd", "-dd", str(HOSTAPD_CONFIG)], "hostapd")

        run(["ip", "addr", "replace", LAB_ADDRESS, "dev", interface])

        print("[+] Validating dnsmasq configuration...")
        run(["dnsmasq", "--test", f"--conf-file={DNSMASQ_CONFIG}"])

        start_process(
            ["dnsmasq", "--no-daemon", f"--conf-file={DNSMASQ_CONFIG}"],
            "dnsmasq",
        )

        # The handler serves the static lab page on 10.42.0.1:8080. Run it
        # from src/ because its existing page path is ../portal/index.html.
        start_process(
            ["python3", "captive-handler.py"],
            "captive portal handler",
            cwd=PROJECT_ROOT / "src",
        )

        # Redirect HTTP requests from clients on this AP to the local demo
        # portal. This does not enable forwarding or capture submitted data.
        nft_rules = f"""table ip {NFT_TABLE} {{
    chain prerouting {{
        type nat hook prerouting priority -100; policy accept;
        iifname \"{interface}\" tcp dport 80 redirect to :8080
    }}
}}
"""
        run(["nft", "delete", "table", "ip", NFT_TABLE], check=False)
        run(["nft", "-f", "-"], input_text=nft_rules)

        print("\n[+] Phishcap lab is running.")
        print("[+] Press Ctrl+C to stop hostapd, dnsmasq, and the lab NAT table.")

        while True:
            for process, name in zip(children, ("hostapd", "dnsmasq", "captive portal handler")):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} stopped unexpectedly (status {process.returncode}).")
            time.sleep(1)

    except KeyboardInterrupt:
        pass
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"[-] Setup failed: {exc}", file=sys.stderr)
        cleanup()
        return 1
    finally:
        cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
