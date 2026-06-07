# Minecraft Services

The production server uses `nix-minecraft` through `../nixos/production-minecraft.nix`.

ATM 10 is a separate live workload test service declared in `../nixos/atm10-live-test.nix`. It is not the final production server.

## Production Server

The production server is named `main` under `services.minecraft-servers.servers`.

Common commands:

```bash
systemctl status minecraft-server-main
journalctl -u minecraft-server-main -f
```

The production world data is stored in `/srv/minecraft/main`.

See `../docs/nix-minecraft-plan.md` for the planned packwiz integration path.

Before changing server type, mods, or world files, create a backup from the repository root:

```bash
sudo ./scripts/backup-world.sh
```

## ATM 10 Live Test

Download the latest ATM 10 server pack from CurseForge. As of the current planning notes, CurseForge lists ATM 10 7.0 for Minecraft 1.21.1 NeoForge and a matching `ServerFiles-7.0.zip`.

After rebuilding NixOS so the `minecraft` user exists, install the test server files:

```bash
sudo ./scripts/install-atm10-test-server.sh ~/Downloads/ServerFiles-7.0.zip
```

The test service has a systemd path condition and will not start until `eula.txt` exists in `/srv/minecraft/atm10-test`. The install script creates that file after extracting the server pack.

Start the live test:

```bash
sudo systemctl stop minecraft-server-main
sudo systemctl start atm10-test-server
journalctl -u atm10-test-server -f
```

Stop the live test before returning to the production server:

```bash
sudo systemctl stop atm10-test-server
sudo systemctl start minecraft-server-main
```

ATM 10 test data is stored in `/srv/minecraft/atm10-test`. To back it up:

```bash
sudo DATA_DIR=/srv/minecraft/atm10-test ./scripts/backup-world.sh
```

## Apply Configuration

```bash
sudo nixos-rebuild switch --flake .#minecraft-home-server
```

All players must use a matching client version for modded tests. Bedrock/Geyser support should be treated as a separate vanilla or Paper server, not part of the ATM 10 live test.
