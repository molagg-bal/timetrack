# NixOS-Modul für timetrack.
#
# Wird normalerweise über ../default.nix eingebunden (aktiviert sich dann selbst).
#
# Danach läuft die App unter http://localhost:54321/ und nutzt eine lokale
# MariaDB, die automatisch eingerichtet wird (Anmeldung per Unix-Socket, kein Passwort).
{ config, lib, pkgs, ... }:

let
  cfg = config.services.timetrack;
  localOnly = builtins.elem cfg.listenAddress [ "127.0.0.1" "::1" "localhost" ];
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

    allowedHosts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "mein-pc.lan" ];
      description = ''
        Zusätzliche Hostnamen, unter denen die Weboberfläche aufgerufen werden darf.
        localhost, 127.0.0.1 und ::1 sind immer erlaubt; alle anderen Namen werden
        als Schutz vor DNS-Rebinding abgewiesen.
      '';
    };

    hardening = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Strenge systemd-Sandbox für den Dienst. Nur zur Fehlersuche abschalten,
        falls der Dienst damit nicht startet.
      '';
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
      # Nur über localhost erreichbar, nie aus dem Netz
      settings.mysqld.bind-address = lib.mkDefault "127.0.0.1";
      ensureDatabases = [ cfg.database.name ];
      ensureUsers = [
        {
          name = "timetrack";
          ensurePermissions = { "${cfg.database.name}.*" = "ALL PRIVILEGES"; };
        }
      ];
    };

    # Zweite Schutzschicht für MariaDB: der Kernel verwirft alle IP-Pakete, die nicht
    # von/zu localhost gehen (der Unix-Socket ist davon nicht betroffen).
    systemd.services.mysql.serviceConfig = lib.mkIf cfg.database.createLocally {
      IPAddressAllow = lib.mkDefault "localhost";
      IPAddressDeny = lib.mkDefault "any";
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
        TIMETRACK_ALLOWED_HOSTS = lib.concatStringsSep "," cfg.allowedHosts;
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
        UMask = "0077";
      } // lib.optionalAttrs cfg.hardening ({
        # Dateisystem komplett schreibgeschützt; die App schreibt keine Dateien
        ProtectSystem = "strict";
        PrivateDevices = true;
        ProtectProc = "invisible";
        ProcSubset = "pid";
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectKernelLogs = true;
        ProtectControlGroups = true;
        ProtectClock = true;
        ProtectHostname = true;
        # keine Sonderrechte, keine neuen Namespaces, nur nötige Systemaufrufe
        CapabilityBoundingSet = "";
        AmbientCapabilities = "";
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
        RemoveIPC = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [ "@system-service" "~@privileged" "~@resources" ];
        # Netzwerk: Unix-Socket (MariaDB) und IP nur für den Webserver
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
      } // lib.optionalAttrs localOnly {
        IPAddressAllow = "localhost";
        IPAddressDeny = "any";
      });
    };
  };
}
