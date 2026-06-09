#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: SSH_PORT=2222 $0 USER@NIXOS_HOST CONFIG_FILE [REMOTE_BASE_DIR]" >&2
  exit 2
fi

target=$1
config_file=$2
remote_base=${3:-.local/share/netprobe}
ssh_port=${SSH_PORT:-}
remote_config=.config/netprobe/netprobe.toml
remote_root=$remote_base/netprobe-package
remote_data=$remote_base/data
remote_source=$remote_base/source
ssh_args=(-o StrictHostKeyChecking=accept-new)
scp_args=(-o StrictHostKeyChecking=accept-new)

if [[ -n $ssh_port ]]; then
  if [[ ! $ssh_port =~ ^[0-9]+$ ]] || ((ssh_port < 1 || ssh_port > 65535)); then
    echo "SSH_PORT must be an integer between 1 and 65535" >&2
    exit 1
  fi
  ssh_args+=(-p "$ssh_port")
  scp_args+=(-P "$ssh_port")
  export NIX_SSHOPTS="${NIX_SSHOPTS:+$NIX_SSHOPTS }-p $ssh_port"
fi

if [[ ! -f $config_file ]]; then
  echo "configuration file not found: $config_file" >&2
  exit 1
fi
if [[ $remote_base = /* || $remote_base = *..* || ! $remote_base =~ ^[A-Za-z0-9_./-]+$ ]]; then
  echo "remote base directory must be a safe relative path without '..': $remote_base" >&2
  exit 1
fi

package=$(nix build --no-link --print-out-paths path:.#netprobe)
echo "Copying $package to $target"
if nix copy --to "ssh://$target" "$package"; then
  echo "Copied the locally built package."
else
  echo "Remote Nix rejected the unsigned local store path; building from source on $target." >&2
  # shellcheck disable=SC2029
  ssh "${ssh_args[@]}" "$target" \
    "mkdir -p \"\$HOME/$remote_source/src\" \"\$HOME/$remote_source/tests\" \"\$HOME/$remote_source/scripts\""
  scp "${scp_args[@]}" flake.nix flake.lock netprobe.example.toml "$target:$remote_source/"
  scp "${scp_args[@]}" src/netprobe.py "$target:$remote_source/src/"
  scp "${scp_args[@]}" tests/test_netprobe.py "$target:$remote_source/tests/"
  scp "${scp_args[@]}" scripts/deploy-nixos.sh "$target:$remote_source/scripts/"
  # shellcheck disable=SC2029
  package=$(ssh "${ssh_args[@]}" "$target" \
    "nix build --no-link --print-out-paths \"path:\$HOME/$remote_source#netprobe\"")
  echo "Built $package on $target"
fi

# Client-side expansion is intentional after validating the relative remote paths above.
# shellcheck disable=SC2029
ssh "${ssh_args[@]}" "$target" "mkdir -p \"\$HOME/.config/netprobe\" \"\$HOME/$remote_base\" \"\$HOME/$remote_data\""
scp "${scp_args[@]}" "$config_file" "$target:$remote_config"

# shellcheck disable=SC2029
ssh "${ssh_args[@]}" "$target" \
  "if [[ -L \"\$HOME/$remote_root\" ]]; then
     ln -sfn '$package' \"\$HOME/$remote_root\"
   else
     nix-store --realise '$package' --add-root \"\$HOME/$remote_root\" --indirect
   fi"

if ! ssh "${ssh_args[@]}" "$target" "loginctl enable-linger \"\$USER\""; then
  echo "Enabling lingering requires remote sudo approval." >&2
  ssh "${ssh_args[@]}" -t "$target" "sudo loginctl enable-linger \"\$USER\""
fi
# shellcheck disable=SC2029
ssh "${ssh_args[@]}" "$target" \
  "\"\$HOME/$remote_root/bin/netprobe\" doctor --config \"\$HOME/$remote_config\" &&
   \"\$HOME/$remote_root/bin/netprobe\" install-service --config \"\$HOME/$remote_config\" --data-dir \"\$HOME/$remote_data\""

echo "Deployment complete."
echo "Status: ssh ${ssh_port:+-p $ssh_port }$target '~/$remote_root/bin/netprobe status'"
echo "Report: ssh ${ssh_port:+-p $ssh_port }$target '~/$remote_root/bin/netprobe report --data-dir ~/$remote_data --run-dir ~/$remote_data/long-term'"
