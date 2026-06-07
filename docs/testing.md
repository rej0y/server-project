# Testing Notes

Use this file to record commands, dates, results, and problems found during the sprint.

## Hardware Validation

|Test|Goal|Result|
|----|----|------|
|BIOS boots and detects CPU/RAM/NVMe|Confirm core hardware works.| |
|CPU stress test|Check temperatures and stability under load.| |
|Memory test|Catch bad RAM or unstable XMP settings.| |
|NVMe SMART check|Confirm SSD health before storing world data.| |
|Wi-Fi detection|Confirm the GC-WBAX210 works under NixOS.| |

## Network Validation

|Test|Goal|Result|
|----|----|------|
|Ping router for 30-60 minutes|Check local packet loss.| |
|Ping stable public host for 30-60 minutes|Check internet packet loss.| |
|Production client joins locally|Confirm LAN connection works on the `nix-minecraft` server.| |
|ATM 10 client joins locally|Confirm live workload test works with matching modpack version.| |
|Systemd service restart keeps world data|Confirm persistent storage works.| |
|VPS tunnel reaches server|Confirm public access if attempted.| |

## Useful Commands

Replace interface names, disk paths, and hostnames before running commands.

```bash
ping -c 300 192.168.1.1
ping -c 300 1.1.1.1
```

```bash
sudo smartctl -a /dev/nvme0n1
```

```bash
systemctl status minecraft-server-main
journalctl -u minecraft-server-main --since "30 minutes ago"
systemctl status atm10-test-server
journalctl -u atm10-test-server --since "30 minutes ago"
```

```bash
./scripts/check-server.sh 127.0.0.1 25565
```

## Demo Evidence To Capture

- A screenshot or terminal output showing NixOS running.
- The relevant NixOS configuration.
- The `nix-minecraft` production service starting successfully.
- A Minecraft client connected to the production server.
- The ATM 10 live test service starting successfully if included.
- A restart test showing that world data persisted.
- Network test output.
- Backup output if the stretch challenge is complete.
