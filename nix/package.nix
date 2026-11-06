{ lib, python3Packages }:

python3Packages.buildPythonApplication {
  pname = "timetrack";
  version = "1.0.0";
  pyproject = true;

  src = lib.cleanSourceWith {
    src = ../.;
    filter = path: type:
      !(builtins.elem (baseNameOf path) [ ".git" ".venv" "__pycache__" ".pytest_cache" "result" ]);
  };

  build-system = [ python3Packages.setuptools ];

  dependencies = with python3Packages; [
    flask
    waitress
    mysqlclient
    xlsxwriter
  ];

  # Tests laufen beim Bauen gegen SQLite (keine MariaDB nötig)
  nativeCheckInputs = with python3Packages; [ pytestCheckHook openpyxl ];

  pythonImportsCheck = [ "timetrack" ];

  meta = {
    description = "Arbeitszeiterfassung (Arbeit/Pause, Urlaub, Krankheit, Gleitzeit) als lokaler Webserver";
    mainProgram = "timetrack";
    platforms = lib.platforms.linux;
  };
}
