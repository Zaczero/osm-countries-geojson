let
  # Update with `nixpkgs-update` command
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/28b5b8af91ffd2623e995e20aee56510db49001a.tar.gz") { };

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
    uv
    ruff

    findutils
    zopfli
    brotli
    zstd

    (writeShellScriptBin "compress-geojson" ''
      set -e
      echo "Compressing GeoJSON files..."
      rm -f geojson/*.geojson.{gz,br,zst}
      files=$(find geojson -type f -name '*.geojson')
      for file in $files; do
        zopfli "$file" &
        brotli --best "$file" &
        zstd --no-progress --ultra -22 --single-thread "$file" &
      done
      wait
    '')
    (writeShellScriptBin "nixpkgs-update" ''
      set -e
      hash=$(
        curl --silent --location \
        https://prometheus.nixos.org/api/v1/query \
        -d "query=channel_revision{channel=\"nixpkgs-unstable\"}" | \
        grep --only-matching --extended-regexp "[0-9a-f]{40}")
      sed -i -E "s|/nixpkgs/archive/[0-9a-f]{40}\.tar\.gz|/nixpkgs/archive/$hash.tar.gz|" shell.nix
      echo "Nixpkgs updated to $hash"
    '')
  ];

  shell' = ''
    export PYTHONNOUSERSITE=1
    export TZ=UTC

    current_python=$(readlink -e .venv/bin/python || echo "")
    current_python=''${current_python%/bin/*}
    [ "$current_python" != "${python'}" ] && rm -rf .venv/

    echo "Installing Python dependencies"
    export UV_COMPILE_BYTECODE=1
    export UV_PYTHON="${python'}/bin/python"
    uv sync --frozen

    echo "Activating Python virtual environment"
    source .venv/bin/activate

    if [ -f .env ]; then
      echo "Loading .env file"
      set -o allexport
      source .env set
      set +o allexport
    else
      echo "Skipped loading .env file (not found)"
    fi
  '';
in
pkgs.mkShellNoCC {
  buildInputs = packages';
  shellHook = shell';
}
