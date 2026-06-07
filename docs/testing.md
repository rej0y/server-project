# Testing Notes

This file records the evidence collected for the NixOS ATM10 home server sprint.

## Hardware Validation

| Test | Goal | Result |
| --- | --- | --- |
| Hardware assembly | Confirm the physical server can boot and run NixOS. | Completed. Server hostname is `altruist`. |
| NixOS install | Confirm NixOS boots and rebuilds from flake config. | Completed. NixOS version `26.05.20260531.b51242d (Yarara)`. |
| CPU stress test | Check temperature and stability under full CPU load. | Completed. 4-hour `stress-ng` run passed 24 CPU workers with 0 failures. |
| Memory test | Catch bad RAM or unstable memory behavior. | Blocked. One 32 GB stick does not boot, so full RAM validation is deferred until replacement/refund is resolved. |
| NVMe layout | Confirm storage is visible and mounted. | Completed. 1.9 TB NVMe with EFI, swap, and Btrfs root/Nix store. |
| Headless boot | Confirm server can boot without a display attached. | Issue found. Motherboard VGA light turns on when no display is attached; dummy HDMI plug is being investigated. |

## CPU Test Evidence

The main completed CPU test ran as `cpu-stress-test.service`.

| Field | Value |
| --- | --- |
| Start | 2026-06-03 22:23:24 MDT |
| End | 2026-06-04 02:23:24 MDT |
| Duration | 4 hours |
| Tool | `stress-ng` |
| Workers | 24 CPU workers |
| Result | 24 passed, 0 failed |
| Exit code | 0 |
| Kernel warnings/errors after test | No entries |
| CPU package temperature near completion | 59.46 C |
| Highest sampled package temperature found in related logs | About 68 C |

The test code was built as a temporary Nix flake so the NixOS host configuration did not need to be permanently modified for the stress test.

## Network Validation

| Test | Goal | Result |
| --- | --- | --- |
| Long-running ping tests | Detect packet loss and outage windows. | Completed for 1.52 days. Report stored under `test/network/netprobe-data/altruist-latest/`. |
| DNS/HTTPS checks | Detect resolver and HTTP connectivity failures. | Completed by the network monitor. |
| VPS throughput checks | Test upload/download path to the VPS. | Completed with `iperf3` on VPS port `5201`. |
| Public IP tracking | Check if apartment public IP changed during the report. | Completed. Public IP changes observed: 0. |
| Local interface counters | Check RX/TX errors and drops. | Completed. RX/TX errors: 0 / 0; RX/TX drops: 0 / 0. |
| FRP SSH access | Confirm server can be reached through VPS. | Completed through `ssh -p 2222 rej0y@66.112.209.106`. |
| FRP ATM10 TCP proxy | Confirm VPS can expose Minecraft TCP port. | Completed. `frp-atm10.service` logged in and started proxy successfully. |

Network report summary:

- Measurement window: 2026-06-04T20:34:41Z to 2026-06-06T09:05:24Z.
- Monitoring duration: 1.52 days.
- All-target Internet outages: 617 totaling 24.7 minutes.
- Longest all-target outage: 17.9 seconds.
- Local gateway packet loss/p95/p99: 2.6228% / 50.50 ms / 391.00 ms.
- Evidence suggests local gateway, Wi-Fi, or router-side instability rather than only upstream Internet instability.

## ATM10 Validation

| Test | Goal | Result |
| --- | --- | --- |
| systemd service active | Confirm ATM10 runs under systemd. | Completed. `atm10.service` active and enabled. |
| Server startup | Confirm Minecraft reaches ready state. | Completed. Journal shows `Done (1.768s)! For help, type "help"` on 2026-06-06 19:15:53 MDT. |
| Client join | Confirm real client can connect. | Completed. Player `rejoyy` joined on 2026-06-06 19:20:36 MDT. |
| Persistent world data | Confirm world directory exists under systemd state. | Completed. World data is under `/var/lib/atm10/world`. |
| Live workload | Confirm server can handle heavy modded interaction. | Completed as a test workload; logs include game-mode changes and large modded explosion tests. |

Observed service facts:

- Service start: 2026-06-06 19:14:54 MDT.
- Main process: `/var/lib/atm10/startserver.sh`.
- Java: OpenJDK 21 headless.
- NeoForge: `21.1.228`.
- Memory current during inspection: about 7.4 GiB.
- Memory peak during inspection: about 23.7 GiB.
- Service restarts: 0 after the inspected active start.

## Known Problems

- Full RAM testing is not complete because one RAM stick is defective.
- The case front glass panel has white haze; NZXT has been contacted.
- The motherboard VGA light appears on reboot when no display is attached.
- The network report shows apartment Wi-Fi/router instability, so a wired Ethernet comparison test is still needed.
