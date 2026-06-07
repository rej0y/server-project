# Earlier nix-minecraft Plan

This file records the earlier plan, but it is not the completed sprint implementation.

The completed sprint implementation uses a native NixOS systemd service for ATM10. See:

```text
nixos/modules/atm10.nix
```

## Why The Plan Changed

The original plan considered `nix-minecraft` for a production Minecraft server and Docker/Compose during early planning. After implementation work, a direct NixOS systemd service was a better fit for this sprint:

- The server pack can be downloaded with a fixed hash using `pkgs.fetchurl`.
- The pack can be unpacked in a Nix derivation.
- systemd can create and manage persistent state with `StateDirectory`.
- The service user, JVM args, server properties, and startup command can all be declared in one Nix module.
- Docker/Compose was not needed for the final ATM10 test server.

## Current Production Direction

Current working service:

```bash
atm10.service
```

Current persistent data path:

```text
/var/lib/atm10
```

Current public access path:

```text
FRP TCP proxy on VPS port 25565
```

## Future Use Of nix-minecraft

`nix-minecraft` may still be useful later for a vanilla, Paper, or smaller modded profile. For this sprint, it should be described as an explored option rather than the completed implementation.
