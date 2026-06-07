# Minecraft Services

The working Minecraft service for this sprint is the native NixOS `atm10.service`.

The original plan considered Docker, Docker Compose, Podman, and `nix-minecraft`, but the completed implementation uses systemd directly through NixOS because it is cleaner for this server.

## ATM10 Test Server

Main config:

```text
nixos/modules/atm10.nix
```

Runtime state:

```text
/var/lib/atm10
```

World data:

```text
/var/lib/atm10/world
```

Service commands:

```bash
systemctl status atm10.service
journalctl -u atm10.service -f
sudo systemctl restart atm10.service
```

The service:

- runs as the `atm10` system user
- uses Java 21 headless
- downloads ATM10 `ServerFiles-7.0.zip`
- runs NeoForge `21.1.228`
- writes selected server properties
- uses `/var/lib/atm10` for persistent state

Important selected properties:

```properties
allow-flight=true
difficulty=normal
gamemode=creative
max-players=50
motd=All the Mods 10
online-mode=true
server-port=25565
simulation-distance=8
view-distance=8
white-list=false
```

JVM args:

```text
-Xms4G
-Xmx20G
-XX:+UseZGC
-XX:+ZGenerational
-XX:+DisableExplicitGC
```

## Public Access

FRP maps the server to the VPS:

```text
altruist 127.0.0.1:25565 -> VPS 66.112.209.106:25565
```

Service names:

```bash
systemctl status frp-atm10.service
systemctl status frp-ssh.service
```

## Validation

Verified on June 6, 2026:

- `atm10.service` active and enabled.
- Minecraft started on `*:25565`.
- Player `rejoyy` logged in and joined the game.
- FRP `atm10` proxy logged in to the VPS and started successfully.

## Not Finished

- A separate final personal modpack profile was not built.
- Full RAM validation is blocked by the defective RAM stick.
- Automated world backups are still future work.
