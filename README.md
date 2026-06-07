# NixOS ATM10 Home Server

## Overview

This project documents my CSE 310 Choose Your Own Adventure module: building a NixOS home server that can host a heavily modded Minecraft server and expose it through a VPS using FRP.

The final sprint result is a working All The Mods 10 test server, managed by a native NixOS systemd service. I originally planned to use Docker or Docker Compose, but changed the design after learning more about NixOS. A native systemd service is simpler for this server because Nix can declare the package download, Java runtime, service user, persistent state directory, firewall behavior, and startup command directly.

The tested server hostname is `altruist`. Public access is routed through the Ubuntu VPS at `66.112.209.106`.

[Software Demo Video](https://youtu.be/WnRHmD0_Yu4)

## Repository Links

- Documentation and evidence repository: <https://github.com/rej0y/server-project>
- NixOS configuration repository: <https://github.com/rej0y/server>

Both repositories were verified as public through the GitHub connector on June 6, 2026.

## Current Status

Completed:

- Physical server assembled.
- NixOS installed and configured on `altruist`.
- SSH configured with public-key authentication and password login disabled.
- FRP configured so the home server connects outward to the Ubuntu VPS.
- Public SSH tunnel works through `ssh -p 2222 rej0y@66.112.209.106`.
- ATM10 service works through `atm10.service`.
- Public ATM10 TCP proxy configured through FRP on VPS port `25565`.
- CPU stress test completed successfully for 4 hours.
- Long-running apartment internet monitor created and report evidence captured.

Open issues:

- NZXT front glass panel has a white haze. NZXT has been contacted, but there was no reply yet when this README was updated.
- One 32 GB RAM stick does not boot. The seller was contacted and a refund/replacement path is in progress. Because of this, full RAM validation is not complete.
- The motherboard VGA light turns on after reboot if no display is connected. A dummy HDMI plug is being investigated.
- A final personal modpack/server profile has not been built yet. The completed server is the functional ATM10 test server.

## Hardware

| Part | Notes |
| --- | --- |
| CPU | Intel Core i9-12900K |
| Motherboard | Gigabyte Z690 UD DDR4 open box |
| Memory | Mushkin Essential DDR4 2x32 GB 3200 MT/s planned; currently one working 32 GB stick |
| Storage | Silicon Power UD90 2 TB Gen4 NVMe |
| Cooling | Arctic Liquid Freezer III Pro 360 |
| Case | NZXT F7 Flow White |
| PSU | Corsair RM750e White |
| Extra fan | NZXT F120Q |
| Networking | Gigabyte GC-WBAX210 Wi-Fi card |

Verified system facts from `altruist`:

- NixOS version: `26.05.20260531.b51242d (Yarara)`
- Kernel: `6.18.33`
- CPU: 24 logical CPUs from the i9-12900K
- Memory currently visible: about 31 GiB
- Main disk: 1.9 TB NVMe with EFI, swap, and Btrfs root/Nix store partitions

## Architecture

The deployment has three main parts:

1. NixOS base system on the home server.
2. Native systemd service for ATM10.
3. FRP tunnel from the home server to the Ubuntu VPS.

The NixOS configuration is organized under [nixos](./nixos):

- [nixos/flake.nix](./nixos/flake.nix) declares the NixOS system.
- [nixos/configuration.nix](./nixos/configuration.nix) imports the hardware config and modules.
- [nixos/modules/atm10.nix](./nixos/modules/atm10.nix) declares the ATM10 server.
- [nixos/modules/frp.nix](./nixos/modules/frp.nix) declares the FRP client proxies.

The ATM10 module:

- Downloads `ServerFiles-7.0.zip` from CurseForge's CDN using `pkgs.fetchurl`.
- Verifies the archive with a fixed SHA-256 hash.
- Unpacks the server pack in a Nix derivation.
- Creates the `atm10` system user and group.
- Uses `/var/lib/atm10` as the persistent systemd state directory.
- Writes `eula.txt`, `user_jvm_args.txt`, and selected `server.properties` values.
- Runs the pack's `startserver.sh` with Java 21.

The FRP module:

- Connects to the VPS at `66.112.209.106:7000`.
- Exposes local SSH port `22` through VPS port `2222`.
- Exposes local Minecraft port `25565` through VPS port `25565`.

## Requirements Report

1. Install and configure NixOS on the home server with SSH, users, firewall/networking, and required packages.

Completed. NixOS is installed on `altruist`, the normal user is `rej0y`, SSH is enabled, password and keyboard-interactive login are disabled, and the system is managed from a flake-based configuration.

2. Enable a persistent Minecraft server deployment.

Completed with a design change. The planned Docker/Compose approach was replaced with a native NixOS systemd service. The working service is `atm10.service`, declared in `modules/atm10.nix`.

3. Configure persistent world storage so world data survives service restarts and redeployments.

Completed for the ATM10 test server. systemd `StateDirectory = "atm10"` maps persistent data to `/var/lib/atm10`, and the live world is stored in `/var/lib/atm10/world`.

4. Test local stability, including hardware stress, network reliability, uptime, and client connection.

Partially completed. CPU stress testing completed successfully, the ATM10 server accepted a real player login, and the network monitor collected long-running evidence. Full RAM validation is blocked because one RAM stick is defective.

5. Configure the VPS as a reverse proxy or tunnel endpoint so outside players can reach the server safely.

Completed for TCP access. The Ubuntu VPS runs `frps.service`, and NixOS runs `frp-ssh.service` and `frp-atm10.service`. The ATM10 proxy logged in successfully and started the `atm10` proxy on June 6, 2026 at 17:55:28 MDT.

Stretch challenge:

Partially completed. I did not finish automated Minecraft backups, but I did complete monitoring beyond the baseline requirement by creating a long-running network monitor and a controlled VPS `iperf3` endpoint.

## Test Evidence

CPU validation:

- `cpu-stress-test.service` started on June 3, 2026 at 22:23:24 MDT.
- It completed on June 4, 2026 at 02:23:24 MDT.
- `stress-ng` ran 24 CPU workers for 14,400 seconds.
- Result: 24 CPU stressors passed, 0 failed.
- Exit code: `0`.
- Recent kernel warnings/errors after the test: none.
- Recorded package temperature near completion: about 59.46 C.
- Other sampled CPU stress logs showed package temperatures up to about 68 C, still below the 100 C critical threshold.

ATM10 validation:

- `atm10.service` is enabled and active.
- Verified active since June 6, 2026 at 19:14:54 MDT.
- Java command uses NeoForge `21.1.228`.
- Service memory peak observed: about 23.7 GiB.
- Minecraft reported `Done (1.768s)! For help, type "help"` on June 6, 2026 at 19:15:53 MDT.
- Player `rejoyy` logged in on June 6, 2026 at 19:20:35 MDT and joined the game at 19:20:36 MDT.

Network validation:

- Long-running report window: June 4, 2026 20:34:41 UTC to June 6, 2026 09:05:24 UTC.
- Monitoring duration: 1.52 days.
- Public IP changes observed: 0.
- Local interface RX/TX errors: 0 / 0.
- Local interface RX/TX drops: 0 / 0.
- Collector task errors: 0.
- Internet outages were detected, with the report pointing mostly toward local gateway or Wi-Fi/router-side instability.

See [docs/testing.md](./docs/testing.md) and [test/network/netprobe-data/altruist-latest/report.md](./test/network/netprobe-data/altruist-latest/report.md) for more evidence.

## Development Environment

- NixOS 26.05
- Nix flakes
- Home Manager
- systemd services
- FRP 0.66.0
- OpenJDK 21 headless
- NeoForge 21.1.228
- ATM10 ServerFiles 7.0
- Ubuntu VPS
- `stress-ng`
- `iperf3`
- `journalctl`
- `git`

## Useful Commands

Rebuild the NixOS server:

```bash
sudo nixos-rebuild switch --flake ~/.config/nixos#altruist
```

Check ATM10:

```bash
systemctl status atm10.service
journalctl -u atm10.service --since "30 minutes ago"
```

Check FRP on NixOS:

```bash
systemctl status frp-ssh.service
systemctl status frp-atm10.service
```

Connect through the VPS:

```bash
ssh -p 2222 rej0y@66.112.209.106
```

Check the Ubuntu VPS:

```bash
ssh -p 29955 john@66.112.209.106
systemctl status frps.service
systemctl status iperf3.service
```

## Useful Websites

- [NixOS Manual](https://nixos.org/manual/nixos/stable/)
- [NixOS options search](https://search.nixos.org/options)
- [FRP](https://github.com/fatedier/frp)
- [All The Mods 10 on CurseForge](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10)
- [AllTheMods/ATM-10 official repository](https://github.com/AllTheMods/ATM-10)
- [NeoForge documentation](https://docs.neoforged.net/)
- [stress-ng](https://wiki.ubuntu.com/Kernel/Reference/stress-ng)
- [iperf3 documentation](https://software.es.net/iperf/)

## Future Work

- Replace or refund the defective RAM stick and run full RAM validation after installing stable memory.
- Resolve the NZXT front glass haze issue.
- Install a dummy HDMI plug or otherwise resolve the headless VGA warning.
- Add automated ATM10 world backups and restore documentation.
- Decide whether to keep ATM10 as the production server or create a separate personal modpack.
- Run a wired Ethernet comparison test to separate Wi-Fi/router issues from upstream ISP issues.
- Keep the walkthrough/demo video updated when the server configuration changes.
