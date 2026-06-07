# Network Plan

## Traffic Types

Minecraft Java uses TCP port `25565`.

GeyserMC Bedrock support usually uses UDP port `19132`.

Normal HTTP reverse proxies are not enough for Minecraft Java or Bedrock traffic. Caddy's standard `reverse_proxy` is designed for HTTP services. For Minecraft, use a TCP/UDP tunnel or a layer 4 proxy instead.

## Recommended Sprint Approach

1. Prove the server works on the local network first.
2. Test Wi-Fi stability before allowing outside players.
3. Add VPS public access only after the local server is stable.

The sprint demo can pass with documented local access if the VPS tunnel is not stable yet.

## Public Access Options

### Option A: frp

Use `frp` when the home server cannot accept inbound connections directly. The home server runs the client, the VPS runs the server, and the VPS exposes the Minecraft port to players.

Pros:

- Designed for exposing internal services through a public server.
- Supports TCP and UDP.
- Good fit for Java and possible Bedrock/Geyser access.

Cons:

- Adds another service to configure and secure.
- Requires careful token/password handling.

### Option B: WireGuard plus VPS port forwarding

Create a WireGuard tunnel between the VPS and the home server. Forward public traffic from the VPS to the home server over the tunnel.

Pros:

- General purpose and secure.
- Useful for more than Minecraft.
- Avoids exposing home network management ports.

Cons:

- Requires firewall and routing configuration.
- Slightly more networking work than frp.

### Option C: Caddy with layer 4 support

Use Caddy only if building Caddy with a layer 4 app/plugin. The default HTTP reverse proxy is not the right tool for Minecraft traffic.

Pros:

- Keeps the Caddy workflow if already familiar.

Cons:

- Requires a custom Caddy build.
- Adds complexity for this sprint.

## Security Checklist

- Keep `online-mode=true` unless there is a specific reason not to.
- Use a whitelist for early testing.
- Open only required ports.
- Do not commit secrets, VPS keys, tokens, or real passwords.
- Back up the world before migration or mod changes.
- Keep the old cloud server as a fallback until the `nix-minecraft` home server runs reliably.
