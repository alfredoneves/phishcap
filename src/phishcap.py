#!/usr/bin/env python3
"""Set up the Phishcap isolated captive-portal lab.

Use only on equipment and wireless spectrum you own or are authorized to test.
This launcher is intended for a contained lab; do not collect real credentials.
"""

import argparse
import os
import re
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
cleanup_done = False
active_interface = None
original_addresses = []
original_managed = None
original_link_up = None
original_interface_type = None
original_connection_uuid = None


def snapshot_interface(interface):
    """Save interface state before changing it so cleanup can restore it."""
    global active_interface, original_addresses, original_managed
    global original_link_up, original_interface_type, original_connection_uuid

    active_interface = interface

    address_result = subprocess.run(
        ["ip", "-o", "addr", "show", "dev", interface],
        capture_output=True, text=True, check=False,
    )
    for line in address_result.stdout.splitlines():
        fields = line.split()
        for family in ("inet", "inet6"):
            if family in fields:
                index = fields.index(family)
                if index + 1 < len(fields):
                    original_addresses.append((family, fields[index + 1]))
                break

    link_result = subprocess.run(
        ["ip", "-o", "link", "show", "dev", interface],
        capture_output=True, text=True, check=False,
    )
    if link_result.stdout:
        flags = re.search(r"<([^>]*)>", link_result.stdout)
        original_link_up = bool(flags and "UP" in flags.group(1).split(","))

    managed_result = subprocess.run(
        ["nmcli", "-g", "GENERAL.MANAGED", "device", "show", interface],
        capture_output=True, text=True, check=False,
    )
    managed_value = managed_result.stdout.strip().lower()
    if managed_value in ("yes", "no"):
        original_managed = managed_value

    # Remember the active NetworkManager profile so cleanup can reconnect
    # the interface instead of merely marking it as managed again.
    connection_result = subprocess.run(
        ["nmcli", "-g", "GENERAL.CON-UUID", "device", "show", interface],
        capture_output=True, text=True, check=False,
    )
    connection_value = connection_result.stdout.strip()
    if connection_value and connection_value != "--":
        original_connection_uuid = connection_value

    type_result = subprocess.run(
        ["iw", "dev", interface, "info"],
        capture_output=True, text=True, check=False,
    )
    type_match = re.search(r"^\s*type\s+(\S+)", type_result.stdout, re.MULTILINE)
    if type_match:
        original_interface_type = type_match.group(1)


def handle_signal(_signum, _frame):
    # Let the normal KeyboardInterrupt/finally path perform cleanup exactly once.
    raise KeyboardInterrupt


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
    parser.add_argument(
        "-c", "--clean",
        action="store_true",
        help="Restore the wireless interface to managed mode and reconnect it.",
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


def clean_interface(interface):
    """Recover an interface after an interrupted or incomplete lab run."""
    print(f"[+] Recovering wireless interface: {interface}")

    commands = [
        ["rfkill", "unblock", "wifi"],
        ["ip", "link", "set", interface, "down"],
        ["iw", "dev", interface, "set", "type", "managed"],
        ["ip", "addr", "del", LAB_ADDRESS, "dev", interface],
        ["ip", "link", "set", interface, "up"],
        ["nmcli", "radio", "wifi", "on"],
        ["nmcli", "device", "set", interface, "managed", "yes"],
    ]

    failed = []
    for command in commands:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        # Deleting the lab address can fail when it is already absent.
        if result.returncode != 0 and command[:3] != ["ip", "addr", "del"]:
            failed.append((command, result.stderr.strip()))

    # The dedicated table may already have been removed by normal cleanup.
    subprocess.run(
        ["nft", "delete", "table", "ip", NFT_TABLE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    # Ask NetworkManager to activate an available saved Wi-Fi profile and
    # obtain its normal DHCP configuration.
    connect = subprocess.run(
        ["nmcli", "device", "connect", interface],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if connect.returncode != 0:
        failed.append((["nmcli", "device", "connect", interface],
                       (connect.stderr or connect.stdout).strip()))

    if failed:
        print("[-] Recovery completed with warnings:")
        for command, error in failed:
            print(f"    {' '.join(command)}: {error or 'command failed'}")
        print("[!] Check NetworkManager and the saved Wi-Fi connection profile.")
        return 1

    print("[+] Interface returned to managed mode; NetworkManager was asked to reconnect.")
    print("[+] Check the connection with: nmcli device status")
    return 0


def cleanup(*_):
    global cleanup_done
    if cleanup_done:
        return
    cleanup_done = True

    print("\n[+] Stopping lab services...")
    for process in reversed(children):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    # Delete only this lab's dedicated table. Absence is an expected state.
    subprocess.run(
        ["nft", "delete", "table", "ip", NFT_TABLE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    # Remove only the lab address; do not flush unrelated addresses that may
    # have been assigned by NetworkManager or another network service.
    if active_interface:
        subprocess.run(
            ["ip", "addr", "del", LAB_ADDRESS, "dev", active_interface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )

        if original_interface_type and original_interface_type != "managed":
            subprocess.run(
                ["ip", "link", "set", active_interface, "down"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            subprocess.run(
                ["iw", "dev", active_interface, "set", "type", original_interface_type],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

        # Restore the link and NetworkManager ownership before reconnecting.
        if original_link_up is not None:
            subprocess.run(
                ["ip", "link", "set", active_interface,
                 "up" if original_link_up else "down"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

        if original_managed is not None:
            subprocess.run(
                ["nmcli", "device", "set", active_interface, "managed", original_managed],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

        if original_managed == "yes" and original_link_up is not False:
            if original_connection_uuid:
                reconnect_command = [
                    "nmcli", "connection", "up", "uuid",
                    original_connection_uuid, "ifname", active_interface,
                ]
            else:
                reconnect_command = ["nmcli", "device", "connect", active_interface]

            subprocess.run(
                reconnect_command,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

        # Re-add any static addresses that were present before the lab started.
        # Dynamic DHCP addresses are restored by reactivating the saved profile.
        for family, address in original_addresses:
            subprocess.run(
                ["ip", family, "addr", "replace", address, "dev", active_interface],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

    print("[+] Lab stopped; firewall table and wireless interface state restored.")


def main():
    banner()
    args = parse_args()

    if os.geteuid() != 0:
        print("[-] Run this script as root (for example: sudo python3 src/phishcap.py).", file=sys.stderr)
        return 1

    if args.interface:
        interface = args.interface
    elif HOSTAPD_CONFIG.is_file():
        interface = read_setting(HOSTAPD_CONFIG, "interface")
    else:
        interface = "wlan0"

    if args.clean:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", interface):
            print("[-] Invalid wireless interface name.", file=sys.stderr)
            return 1
        return clean_interface(interface)

    if not HOSTAPD_CONFIG.is_file() or not DNSMASQ_CONFIG.is_file():
        print("[-] Configuration files not found. Run this script from the project checkout.", file=sys.stderr)
        return 1

    ssid = args.ssid or read_setting(HOSTAPD_CONFIG, "ssid")
    validate_options(interface, ssid)

    # Keep both services bound to the same selected wireless interface.
    update_setting(HOSTAPD_CONFIG, "interface", interface)
    update_setting(HOSTAPD_CONFIG, "ssid", ssid)
    update_setting(DNSMASQ_CONFIG, "interface", interface)

    print(f"[+] Interface: {interface}")
    print(f"[+] SSID: {ssid}")
    print("[!] Use only with your own test devices in an isolated lab.")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        print("[+] Stopping existing hostapd and dnsmasq services...")
        run(["systemctl", "stop", "hostapd", "dnsmasq"])

        snapshot_interface(interface)
        run(["nmcli", "device", "set", interface, "managed", "no"])
        run(["rfkill", "unblock", "wifi"])

        print("[+] Preparing wireless interface...")
        run(["ip", "link", "set", interface, "down"])
        run(["iw", "dev", interface, "set", "type", "managed"])
        run(["ip", "addr", "flush", "dev", interface])
        run(["ip", "link", "set", interface, "up"])

        # Keep verbose hostapd diagnostics in the project log file.
        hostapd_log = PROJECT_ROOT / "hostapd_logs.txt"
        start_process(
            ["hostapd", "-dd", "-f", str(hostapd_log), str(HOSTAPD_CONFIG)],
            "hostapd",
        )

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
        # A missing table is normal on the first run; suppress that message.
        subprocess.run(
            ["nft", "delete", "table", "ip", NFT_TABLE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        run(["nft", "-f", "-"], input_text=nft_rules)

        print("\n[+] Phishcap lab is running.")
        print("[+] Press Ctrl+C to stop hostapd, dnsmasq, and the lab NAT table.")

        while True:
            for process, name in zip(children, ("hostapd", "dnsmasq", "captive portal handler")):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} stopped unexpectedly (status {process.returncode}).")
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[+] Ctrl+C received; shutting down cleanly.")
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"[-] Setup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
