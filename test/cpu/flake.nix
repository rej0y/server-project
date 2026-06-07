{
  description = "4-hour CPU stress test for NixOS servers";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;

      mkCpuStressScript = pkgs:
        pkgs.writeShellApplication {
          name = "cpu-stress-4h";
          runtimeInputs = with pkgs; [
            stress-ng
            coreutils
            procps
            util-linux
            systemd
          ];

          text = ''
            set -euo pipefail

            duration="''${CPU_STRESS_DURATION:-4h}"
            workers="''${CPU_STRESS_WORKERS:-0}"
            log_dir="''${CPU_STRESS_LOG_DIR:-./cpu-stress-logs}"

            mkdir -p "$log_dir"
            log="$log_dir/stress-ng-$(date -u +%Y%m%dT%H%M%SZ).log"

            {
              echo "=== CPU stress test ==="
              echo "Started:          $(date -Is)"
              echo "Duration:         $duration"
              echo "Workers:          $workers"
              echo "Host:             $(hostname)"
              echo "Kernel:           $(uname -a)"
              echo "Configured CPUs:  $(getconf _NPROCESSORS_CONF)"
              echo "Online CPUs:      $(getconf _NPROCESSORS_ONLN)"
              echo "Log file:         $log"
              echo
            } | tee -a "$log"

            extra_args=()
            if [ "$(id -u)" -eq 0 ]; then
              extra_args+=(--klog-check --interrupts)
            fi

            set +e
            stress-ng \
              --cpu "$workers" \
              --cpu-method all \
              --verify \
              --timeout "$duration" \
              --metrics-brief \
              --times \
              --tz \
              --timestamp \
              --log-file "$log" \
              "''${extra_args[@]}"
            rc="$?"
            set -e

            {
              echo
              echo "Finished:         $(date -Is)"
              echo "stress-ng exit:   $rc"
              echo
              echo "Recent kernel warnings/errors:"
              journalctl -k -p warning..alert --since "5 hours ago" --no-pager || true
            } | tee -a "$log"

            exit "$rc"
          '';
        };
    in
    {
      packages = forAllSystems
        (system:
          let
            pkgs = import nixpkgs { inherit system; };
          in
          {
            cpu-stress-4h = mkCpuStressScript pkgs;
            default = self.packages.${system}.cpu-stress-4h;
          });

      apps = forAllSystems
        (system:
          {
            cpu-stress-4h = {
              type = "app";
              program = "${self.packages.${system}.cpu-stress-4h}/bin/cpu-stress-4h";
            };

            default = self.apps.${system}.cpu-stress-4h;
          });

      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.cpuStressTest;
          script = mkCpuStressScript pkgs;
        in
        {
          options.services.cpuStressTest = {
            enable = lib.mkEnableOption "a one-shot CPU stress test service";

            duration = lib.mkOption {
              type = lib.types.str;
              default = "4h";
              description = "How long to run the CPU stress test.";
            };

            workers = lib.mkOption {
              type = lib.types.str;
              default = "0";
              description = "Number of stress-ng CPU workers. 0 means all configured CPUs.";
            };

            logDir = lib.mkOption {
              type = lib.types.path;
              default = "/var/log/cpu-stress-test";
              description = "Directory where stress test logs are written.";
            };

            runOnBoot = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Start the stress test automatically at boot.";
            };
          };

          config = lib.mkIf cfg.enable {
            environment.systemPackages = [ script ];

            systemd.tmpfiles.rules = [
              "d ${toString cfg.logDir} 0755 root root -"
            ];

            systemd.services.cpu-stress-test = {
              description = "4-hour CPU stress test";
              wantedBy = lib.mkIf cfg.runOnBoot [ "multi-user.target" ];

              serviceConfig = {
                Type = "oneshot";
                ExecStart = "${script}/bin/cpu-stress-4h";
                TimeoutStartSec = "5h";
                Environment = [
                  "CPU_STRESS_DURATION=${cfg.duration}"
                  "CPU_STRESS_WORKERS=${cfg.workers}"
                  "CPU_STRESS_LOG_DIR=${toString cfg.logDir}"
                ];
              };
            };
          };
        };
    };
}
