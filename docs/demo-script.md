# Demo Script

## Short Walkthrough

1. State the goal: build a NixOS home server that runs a heavily modded Minecraft test server and exposes it through a VPS with FRP.
2. Show the hardware list and mention the two hardware issues: hazy NZXT glass and one defective RAM stick.
3. Show the NixOS configuration repository and the local copied files in `nixos/`.
4. Open `nixos/modules/atm10.nix` and explain:
   - `atm10Version`
   - fixed-hash `fetchurl`
   - unpack derivation
   - `atm10` system user/group
   - `StateDirectory = "atm10"`
   - JVM args
   - selected `server.properties`
   - `exec ./startserver.sh`
5. Open `nixos/modules/frp.nix` and explain:
   - SSH proxy from local port `22` to VPS port `2222`
   - ATM10 proxy from local port `25565` to VPS port `25565`
6. Show service status:

```bash
systemctl status atm10.service
systemctl status frp-ssh.service
systemctl status frp-atm10.service
```

7. Show relevant logs:

```bash
journalctl -u atm10.service --since "2026-06-06 19:14:00" --until "2026-06-06 19:21:00"
```

Important lines to show:

- Server started on `*:25565`.
- `Done (1.768s)! For help, type "help"`.
- Player `rejoyy` logged in and joined.

8. Demonstrate the running server from a matching ATM10 client.
9. Show `/var/lib/atm10/world` or explain that this is the persistent world path managed by systemd state.
10. Show CPU test evidence:

```bash
journalctl -u cpu-stress-test.service --since "2026-06-03 22:23:00"
```

11. Show the network report:

```text
test/network/netprobe-data/altruist-latest/report.md
```

12. Explain what was not completed:
   - full RAM validation, blocked by defective RAM stick
   - final personal modpack, because hardware and network issues took priority
   - backup automation, not finished

## Important Talking Points

- I changed the design from Docker/Compose to native NixOS systemd because it better matches NixOS.
- I wrote the NixOS service/configuration manually while using AI as an explainer/reviewer.
- The CPU and network test flakes/scripts were AI-assisted test tooling and did not permanently modify the NixOS server configuration.
- The server is functional as an ATM10 test server, but not yet finalized as a production personal Minecraft server.
- The old/current cloud setup should remain a fallback until RAM and network stability are fully resolved.
