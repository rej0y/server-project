# NixOS Minecraft Home Server

This project documents and deploys a NixOS-based home server for hosting Minecraft with `nix-minecraft`. The goal is to produce a reproducible server configuration, validate the hardware and network, and demonstrate a working server that can survive restarts through persistent world storage.

## Sprint Scope

The main sprint deliverable is a stable local Minecraft server managed by `nix-minecraft`. ATM 10 is used as a live workload test for the new hardware, not as the final production server. Public access through a VPS, automated backups, monitoring, Bedrock compatibility, and migration of the old cloud world are stretch goals.

This scope is intentional. Hardware shipping, Wi-Fi stability, NixOS setup, Minecraft configuration, live workload testing, and VPS routing are each large enough to delay the project. A working local server with clear documentation is the baseline that protects the demo.

## Current Decision

For the graded demonstration, the recommended path is:

1. Build and validate the physical server.
2. Install NixOS and commit the system configuration.
3. Run the production `nix-minecraft` server locally with persistent storage.
4. Run ATM 10 locally as a live workload test if the hardware and base server are stable.
5. Document testing results for hardware, network, server uptime, and world persistence.
6. Attempt VPS public access only after the local server is stable.

The old cloud server should be treated as a backup or legacy server until the new server is proven stable. Migrating the existing world should not be part of the minimum requirement. A fresh test world is safer for the demonstration.

## Vanilla, Bedrock, And Mods

The server has two competing goals:

- Bedrock support, likely through GeyserMC, is useful if Laura still needs to join from Bedrock.
- ATM 10 on NeoForge is useful for testing the new hardware under heavier load.

Those goals conflict because Bedrock players cannot normally join a Java server that requires client-side mods. The clean plan is to keep the production server managed by `nix-minecraft`, use ATM 10 only for live testing, and run a separate vanilla or Paper server with GeyserMC later if Bedrock support is still needed.

## Hardware

Planned server hardware:

| Part | Notes |
| --- | --- |
| CPU | Intel Core i9-12900K |
| Motherboard | Gigabyte Z690 UD DDR4 open box |
| Memory | Mushkin Essential DDR4 2x32 GB 3200 MT/s |
| Storage | Silicon Power UD90 2 TB Gen4 NVMe |
| Cooling | Arctic Liquid Freezer III Pro 360 |
| Case | NZXT F7 Flow White |
| PSU | Corsair RM750e White |
| Extra fan | NZXT F120Q |
| Networking | Gigabyte GC-WBAX210 Wi-Fi card |

The total build cost is approximately $1000.

## Requirements

1. Install and configure NixOS on the home server with SSH, users, firewall rules, Wi-Fi, and required packages.
2. Enable a reproducible Minecraft server deployment using `nix-minecraft`.
3. Configure persistent world storage and backups so data survives server restarts and redeployments.
4. Test local stability, including hardware stress, memory, SSD health, network reliability, uptime, and client connection.
5. Configure or document a VPS TCP/UDP tunnel or proxy path so outside players can reach the server safely.

Stretch challenge: add automated backups or monitoring for Minecraft world data and server status.

## Implementation Plan

### Phase 1: Hardware Validation

- Assemble the server and update BIOS if needed.
- Confirm CPU temperature under load.
- Run a memory stability test before trusting the RAM.
- Check NVMe health and run a disk write/read test.
- Confirm Wi-Fi adapter support under NixOS.
- Run long ping or packet-loss tests against the router and a stable public host.

### Phase 2: NixOS Base System

- Install NixOS.
- Configure users, SSH, sudo, firewall rules, networking, and required packages.
- Commit the first working system configuration.
- Rebuild from the committed configuration to prove reproducibility.

### Phase 3: Production Minecraft Service

- Configure `nix-minecraft` through the flake and `services.minecraft-servers`.
- Store world data in `/srv/minecraft/main`.
- Restart the server and confirm that world data remains.
- Connect from a Minecraft client on the local network.
- Record systemd status, journal logs, uptime, port usage, and connection behavior.

### Phase 4: ATM 10 Live Test

- Install the official ATM 10 server pack into `/srv/minecraft/atm10-test`.
- Stop the production server before starting the ATM 10 test if both use port `25565`.
- Connect from a matching ATM 10 client on the local network.
- Record startup time, memory use, CPU load, TPS behavior, and connection behavior.

### Phase 5: Public Access

- Keep the local server working before exposing it.
- Test whether the apartment Wi-Fi is stable enough for outside players.
- Use the VPS as a TCP/UDP tunnel endpoint or documented public access layer.
- Do not rely on a normal HTTP reverse proxy for Minecraft traffic.
- Keep firewall rules narrow and document open ports.

### Phase 6: Backups Or Monitoring

- Add a script or service that backs up the world directory.
- Record backup location, frequency, and restore steps.
- Optionally add a simple status check that records whether the server port is reachable.

## Suggested Repository Layout

```text
.
|-- README.md
|-- flake.nix
|-- sprint_time_log.md
|-- .gitignore
|-- nixos/
|   |-- configuration.example.nix
|   |-- hardware-configuration.example.nix
|   |-- production-minecraft.nix
|   `-- atm10-live-test.nix
|-- minecraft/
|   `-- README.md
|-- scripts/
|   |-- install-atm10-test-server.sh
|   |-- backup-world.sh
|   `-- check-server.sh
`-- docs/
    |-- testing.md
    |-- nix-minecraft-plan.md
    |-- network-plan.md
    `-- demo-script.md
```

## Learning Sources

- [NixOS Manual](https://nixos.org/manual/nixos/stable/)
- [nix-minecraft](https://github.com/Infinidoge/nix-minecraft)
- [packwiz](https://packwiz.infra.link/)
- [All the Mods 10 - ATM10 on CurseForge](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10)
- [AllTheMods/ATM-10 official repository](https://github.com/AllTheMods/ATM-10)
- [Caddy Reverse Proxy Quick Start](https://caddyserver.com/docs/quick-starts/reverse-proxy)
- [frp](https://github.com/fatedier/frp)
- [WireGuard Quick Start](https://www.wireguard.com/quickstart/)
- [caddy-l4](https://github.com/mholt/caddy-l4)
- [GeyserMC Wiki](https://geysermc.org/wiki/geyser/)
## Demo Checklist

- Show the physical server or describe the hardware.
- Show the NixOS configuration files.
- Explain that `hardware-configuration.example.nix` is replaced by the real generated hardware configuration after installation.
- Rebuild or explain how the system is rebuilt.
- Start or restart the production `minecraft-server-main` service.
- Connect to the production server from a Minecraft client.
- Start the `atm10-test-server` service and connect from a matching ATM 10 client if the live test is included in the demo.
- Show that world data persists after restart.
- Show local network or VPS connectivity test results.
- Show backup or monitoring output if the stretch challenge is complete.
