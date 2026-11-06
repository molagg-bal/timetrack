# Einstiegspunkt für configuration.nix:
#
#   imports = [ (fetchTarball "https://github.com/BENUTZERNAME/timetrack/archive/refs/heads/main.tar.gz") ];
#
# Importieren genügt: der Dienst wird damit automatisch aktiviert (abschaltbar
# mit services.timetrack.enable = false;).
{ lib, ... }:
{
  imports = [ ./nix/module.nix ];
  services.timetrack.enable = lib.mkDefault true;
}
