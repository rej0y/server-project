{ config, lib, pkgs, ... }:

let
  atm10Version = "7.0";
  atm10CdnPath = "8094/893";
  atm10FileName = "ServerFiles-${atm10Version}.zip";

  atm10ServerZip = pkgs.fetchurl {
    url = "https://mediafilez.forgecdn.net/files/${atm10CdnPath}/${atm10FileName}";
    hash = "sha256-b3xzqChHx5YcrF2cV5svL096K2RtqA84soyKQG4nn2A=";
  };

  atm10Pack = pkgs.stdenvNoCC.mkDerivation {
    pname = "atm10-server-pack";
    version = atm10Version;
    src = atm10ServerZip;
    nativeBuildInputs = with pkgs; [ unzip ];
    unpackPhase = ''
      mkdir source
      cd source
      unzip -q "$src"
    '';
    installPhase = ''
      mkdir -p $out/share/atm10
      cp -r . $out/share/atm10
    '';
  };

  atm10JvmArgs = pkgs.writeText "atm10-user_jvm_args.txt" ''
    -Xms4G
    -Xmx20G
    -XX:+UseZGC
    -XX:+ZGenerational
    -XX:+DisableExplicitGC
  '';

  atm10ServerProperties = pkgs.writeText "atm10-server.properties" ''
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
  '';
in
{
  users = {
    users.atm10 = {
      isSystemUser = true;
      group = "atm10";
      home = "/var/lib/atm10";
    };
    groups.atm10 = {};
  };

  systemd.services.atm10 = {
    description = "All The Mods 10 Minecraft Server";
    wantedBy = [ "multi-user.target" ];

    path = with pkgs; [
      coreutils
      gawk
      jdk21_headless
    ];

    serviceConfig = {
      User = "atm10";
      Group = "atm10";
      StateDirectory = "atm10";
      WorkingDirectory = "/var/lib/atm10";
      Environment = [
        "ATM10_JAVA=${pkgs.jdk21_headless}/bin/java"
        "ATM10_RESTART=false"
      ];
    };

    script = ''
      echo "Installing ATM10 pack into /var/lib/atm10"

      if [ ! -f .pack-version ] || [ "$(cat .pack-version)" != "${atm10Version}" ]; then
        cp -r --no-preserve=mode,ownership ${atm10Pack}/share/atm10/. /var/lib/atm10/
        chmod -R u+rwX,g+rX,o-rwx /var/lib/atm10
        chmod +x /var/lib/atm10/startserver.sh
        echo "${atm10Version}" > /var/lib/atm10/.pack-version
      fi

      echo "ATM10 pack installed"
      echo "eula=true" > eula.txt
      install -m 0640 ${atm10JvmArgs} user_jvm_args.txt
      install -m 0640 ${atm10ServerProperties} server.properties
      exec ./startserver.sh
    '';
  };
}
