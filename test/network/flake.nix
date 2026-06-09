{
  description = "Long-running, evidence-oriented Internet connection monitor";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          runtimeInputs = with pkgs; [
            bind.dnsutils
            coreutils
            curl
            iperf3
            iproute2
            iputils
            iw
            mtr
            procps
            systemd
          ];
          netprobe = pkgs.writeShellApplication {
            name = "netprobe";
            inherit runtimeInputs;
            text = ''
              export NETPROBE_RUNTIME_PATH="$PATH"
              export NETPROBE_DEFAULT_CONFIG="${./netprobe.example.toml}"
              exec ${pkgs.python3}/bin/python ${./src/netprobe.py} "$@"
            '';
          };
          iperfServer = pkgs.writeShellApplication {
            name = "netprobe-iperf-server";
            runtimeInputs = [ pkgs.iperf3 ];
            text = ''
              exec iperf3 --server "$@"
            '';
          };
        in
        {
          default = netprobe;
          inherit netprobe;
          iperf-server = iperfServer;
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.netprobe}/bin/netprobe";
          meta.description = "Collect and report long-running Internet stability evidence";
        };
        netprobe = {
          type = "app";
          program = "${self.packages.${system}.netprobe}/bin/netprobe";
          meta.description = "Collect and report long-running Internet stability evidence";
        };
        iperf-server = {
          type = "app";
          program = "${self.packages.${system}.iperf-server}/bin/netprobe-iperf-server";
          meta.description = "Run the controlled iperf3 server endpoint";
        };
      });

      checks = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          tests = pkgs.runCommand "netprobe-tests"
            { nativeBuildInputs = [ pkgs.python3 pkgs.shellcheck ]; }
            ''
              export PYTHONPATH=${./src}
              export NETPROBE_DEFAULT_CONFIG=${./netprobe.example.toml}
              python -m py_compile ${./src/netprobe.py}
              python -m unittest discover -s ${./tests} -v
              shellcheck ${./scripts/deploy-nixos.sh}
              touch "$out"
            '';
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = [
              self.packages.${system}.netprobe
              pkgs.python3
            ];
          };
        });
    };
}
