# Demo Script

## Short Walkthrough

1. Explain the goal: a reproducible NixOS home server using `nix-minecraft`.
2. Show the hardware list and why the CPU, RAM, SSD, and Wi-Fi card were selected.
3. Show the NixOS configuration.
4. Show the `nix-minecraft` production service configuration.
5. Start or restart the `minecraft-server-main` service.
6. Join the production server from a Minecraft client on the local network.
7. Optionally start `atm10-test-server` and join from a matching ATM 10 client as the live workload test.
8. Show persistent world storage.
9. Show test results for hardware, network, and uptime.
10. Show backups or monitoring if completed.
11. Explain whether VPS public access was completed or documented as future work.

## Important Talking Points

- Minecraft benefits from strong single-core CPU performance, and ATM 10 gives a heavier live workload for testing the i9-12900K.
- The first milestone is local stability, not public exposure.
- Bedrock support and ATM 10 conflict, so they should be treated as separate server profiles.
- The old cloud server should stay available until the home server is proven stable.
- The time log includes research, planning, hardware selection, configuration, testing, and documentation.
