# nix-minecraft Production Plan

The production server should be managed with `nix-minecraft`, not the temporary ATM 10 live-test service.

The current production module is `../nixos/production-minecraft.nix`. It declares a `main` server under:

```nix
services.minecraft-servers.servers.main
```

The generated systemd service is expected to be:

```bash
minecraft-server-main.service
```

## Current Baseline

The current baseline uses:

```nix
pkgs.neoforgeServers.neoforge-1_21_1
```

This proves that `nix-minecraft` can create and manage the production server. It is not the final modpack state.

## Next Step

Use packwiz with `nix-minecraft` so the production server can symlink or copy declared `mods`, `config`, and server-specific files into `/srv/minecraft/main`.

The intended shape is:

```nix
let
  modpack = pkgs.fetchPackwizModpack {
    url = "https://example.com/pack.toml";
    packHash = "sha256-...";
  };
in
{
  services.minecraft-servers.servers.main = {
    enable = true;
    package = pkgs.neoforgeServers.neoforge-1_21_1;
    symlinks = {
      mods = "${modpack}/mods";
    };
    files = {
      config = "${modpack}/config";
    };
  };
}
```

Use a stable URL, tag, or commit for the packwiz `pack.toml` so the build remains reproducible.

## ATM 10 Role

ATM 10 is only a live workload test. It should be started manually with:

```bash
sudo systemctl start atm10-test-server
```

Stop the production server first if both are configured to use port `25565`.
