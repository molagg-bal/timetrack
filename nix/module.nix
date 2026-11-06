# NixOS-Modul für timetrack.
#
# Wird normalerweise über ../default.nix eingebunden (aktiviert sich dann selbst).
#
# Danach läuft die App unter http://localhost:54321/ und nutzt eine lokale
# MariaDB, die automatisch eingerichtet wird (Anmeldung per Unix-Socket, kein Passwort).
{ config, lib, pkgs, ... }:

let
  cfg = config.services.timetrack;
  states = [ "BW" "BY" "BE" "BB" "HB" "HH" "HE" "MV" "NI" "NW" "RP" "SL" "SN" "ST" "SH" "TH" ];
in
{
  options.services.timetrack = {
    enable = lib.mkEnableOption "timetrack (Arbeitszeiterfassung)";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "Das timetrack-Paket.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 54321;
      description = "Port des Webservers.";
    };

    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Adresse, auf der der Webserver lauscht (Standard: nur lokal).";
    };

    holidayState = lib.mkOption {
      type = lib.types.enum states;
      default = "NI";
      description = "Bundesland für die automatisch eingetragenen Feiertage (NF).";
    };

    database = {
      createLocally = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Lokale MariaDB samt Datenbank und Benutzer automatisch einrichten.";
      };
      name = lib.mkOption {
        type = lib.types.str;
        default = "timetrack";
        description = "Name der Datenbank.";
      };
      socket = lib.mkOption {
        type = lib.types.str;
        default = "/run/mysqld/mysqld.sock";
        description = "Unix-Socket des MariaDB/MySQL-Servers.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    services.mysql = lib.mkIf cfg.database.createLocally {
      enable = true;
      package = lib.mkDefault pkgs.mariadb;
      ensureDatabases = [ cfg.database.name ];
      ensureUsers = [
        {
          name = "timetrack";
          ensurePermissions = { "${cfg.database.name}.*" = "ALL PRIVILEGES"; };
        }
      ];
    };

    users.users.timetrack = {
      isSystemUser = true;
      group = "timetrack";
      description = "timetrack service user";
    };
    users.groups.timetrack = { };

    systemd.services.timetrack = {
      description = "timetrack Arbeitszeiterfassung";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ] ++ lib.optional cfg.database.createLocally "mysql.service";
      requires = lib.optional cfg.database.createLocally "mysql.service";

      environment = {
        TIMETRACK_LISTEN = cfg.listenAddress;
        TIMETRACK_PORT = toString cfg.port;
        TIMETRACK_HOLIDAY_STATE = cfg.holidayState;
        TIMETRACK_DB_NAME = cfg.database.name;
        TIMETRACK_DB_USER = "timetrack";
        TIMETRACK_DB_SOCKET = cfg.database.socket;
      };

      serviceConfig = {
        ExecStart = lib.getExe cfg.package;
        User = "timetrack";
        Group = "timetrack";
        Restart = "on-failure";
        RestartSec = 5;
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectHome = true;
        ProtectSystem = "full";
      };
    };
  };
}
