{ config, lib, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./modules/frp.nix
    ./modules/atm10.nix
  ];

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  boot.loader = {
    systemd-boot.enable = true;
    efi.canTouchEfiVariables = true;
    timeout = 0;
  };

  networking = {
    hostName = "altruist";
    networkmanager.enable = true;
  };

  users.users.rej0y = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINpkmA0Ako1CSQTj2grWHPC55etVCaepAIs+qv9ljbAF rej0y@charity"
    ];
  };

  security.rtkit.enable = true;

  environment.systemPackages = with pkgs; [
  ];

  services = {
    pipewire = {
      enable = true;
      alsa = {
        enable = true;
        support32Bit = true;
      };
      pulse.enable = true;
    };

    openssh = {
      enable = true;
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
      };
    };
  };

  time.timeZone = "America/Boise";

  system.stateVersion = "26.05";
}
