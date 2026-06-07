{ config, lib, pkgs, ... }:

{
  services.frp.instances = {
    ssh = {
      enable = true;
      role = "client";

      settings = {
        serverAddr = "66.112.209.106";
        serverPort = 7000;

        proxies = [
          {
            name = "ssh";
            type = "tcp";
            localIP = "127.0.0.1";
            localPort = 22;
            remotePort = 2222;
          }
        ];
      };
    };

    atm10 = {
      enable = true;
      role = "client";

      settings = {
        serverAddr = "66.112.209.106";
        serverPort = 7000;

        proxies = [
          {
            name = "atm10";
            type = "tcp";
            localIP = "127.0.0.1";
            localPort = 25565;
            remotePort = 25565;
          }
        ];
      };
    };
  };
}
