# Network Plan

## Traffic Types

Minecraft Java uses TCP port `25565`.

GeyserMC Bedrock support usually uses UDP port `19132`, but Bedrock/Geyser was not completed in this sprint. ATM10 is a Java modpack and requires matching Java/NeoForge client mods.

## Implemented Public Access

The completed public access path uses FRP.

```text
Minecraft client
    -> Ubuntu VPS 66.112.209.106:25565
    -> frps on VPS port 7000
    -> frp-atm10.service on altruist
    -> 127.0.0.1:25565 on altruist
    -> atm10.service
```

NixOS FRP client services:

- `frp-ssh.service`: local `127.0.0.1:22` to VPS `2222`.
- `frp-atm10.service`: local `127.0.0.1:25565` to VPS `25565`.

Ubuntu VPS services:

- `frps.service`: active, enabled, running `/opt/frp/frps -c /opt/frp/frps.toml`.
- `iperf3.service`: active, enabled, running `/usr/bin/iperf3 --server --port 5201`.

Verified NixOS FRP journal facts:

- `frp-ssh.service` started successfully on June 6, 2026 at 17:50:04 MDT.
- `frp-atm10.service` started successfully on June 6, 2026 at 17:55:28 MDT.
- Both clients logged in to the FRP server and started their proxies successfully.

## Network Monitoring

A long-running network monitor was used to evaluate apartment internet stability.

It collected:

- Ping samples to the local gateway, VPS, Cloudflare, Google, and Quad9.
- DNS checks.
- HTTP connectivity checks.
- MTR route snapshots.
- Public IP observations.
- Route and Wi-Fi/link observations.
- Controlled upload/download throughput tests to the VPS.

The latest local evidence bundle is in:

```text
test/network/netprobe-data/altruist-latest/
```

Important result:

The report showed repeated all-target outages and nonzero local-gateway packet loss. Because the local gateway was affected, the next practical test is an Ethernet comparison. If wired Ethernet removes the gateway loss, the main problem is likely Wi-Fi. If gateway loss continues on Ethernet, investigate the router or apartment network.

## Security Notes

- SSH password authentication is disabled on the NixOS server.
- FRP lets the home server initiate the connection outward, avoiding inbound apartment port forwarding.
- Minecraft RCON is not enabled in the final ATM10 server properties.
- `online-mode=true` is enabled.
- Do not commit FRP tokens, VPS passwords, private keys, or Minecraft admin passwords.

## Future Work

- Add optional Bedrock/Geyser support only on a separate vanilla or Paper profile.
- Add automated backups for `/var/lib/atm10/world`.
- Run a wired Ethernet comparison test.
- Re-check VPS firewall rules after final deployment.
