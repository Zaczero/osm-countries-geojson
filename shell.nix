let
  # Update with `nixpkgs-update` command
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/4284c2b73c8bce4b46a6adf23e16d9e2ec8da4bb.tar.gz") { };

  pythonLibs = with pkgs; [
    stdenv.cc.cc.lib
    zlib.out
  ];
  python' = with pkgs; symlinkJoin {
    name = "python";
    paths = [ python312 ];
    buildInputs = [ makeWrapper ];
    postBuild = ''
      wrapProgram "$out/bin/python3.12" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath pythonLibs}"
    '';
  };

  packages' = with pkgs; [
    python'
    poetry
    ruff

    findutils
    pigz
    brotli
    zstd

    (writeShellScriptBin "compress-geojson" ''
      set -e
      echo "Compressing GeoJSON files..."
      files=$(find geojson -type f -name '*.geojson')
      pigz -11 --force --keep $files &
      for file in $files; do
        brotli --best --force "$file" &
        zstd --quiet --ultra -22 --force -T0 "$file" &
      done
      wait
    '')
    (writeShellScriptBin "nixpkgs-update" ''
      set -e
      hash=$(git ls-remote https://github.com/NixOS/nixpkgs nixpkgs-unstable | cut -f 1)
      sed -i -E "s|/nixpkgs/archive/[0-9a-f]{40}\.tar\.gz|/nixpkgs/archive/$hash.tar.gz|" shell.nix
      echo "Nixpkgs updated to $hash"
    '')
  ];

  shell' = ''
    current_python=$(readlink -e .venv/bin/python || echo "")
    current_python=''${current_python%/bin/*}
    [ "$current_python" != "${python'}" ] && rm -r .venv

    echo "Installing Python dependencies"
    export POETRY_VIRTUALENVS_IN_PROJECT=1
    poetry env use "${python'}/bin/python"
    poetry install --no-root --compile

    echo "Activating Python virtual environment"
    source .venv/bin/activate

    # Development environment variables
    export PYTHONNOUSERSITE=1
    export TZ=UTC

    if [ -f .env ]; then
      echo "Loading .env file"
      set -o allexport
      source .env set
      set +o allexport
    fi
  '';
in
pkgs.mkShellNoCC {
  buildInputs = packages';
  shellHook = shell';
}
