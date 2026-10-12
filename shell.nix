let
  # Update with `nixpkgs-update` command
  pkgs =
    import
      (fetchTarball "https://github.com/NixOS/nixpkgs/archive/8edc0c72e3a38faf5434e40d1f19431125fe4b30.tar.gz")
      { };

  pythonLibs = with pkgs; [
    zlib.out
    stdenv.cc.cc.lib
  ];
  python' =
    with pkgs;
    symlinkJoin {
      name = "python";
      paths = [ python314 ];
      buildInputs = [ makeWrapper ];
      postBuild = ''
        wrapProgram "$out/bin/python3.14" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath pythonLibs}"
      '';
    };

  packages' = with pkgs; [
    python'

    git
    uv

    (writeShellScriptBin "generate-geojson" ''
      exec python generate.py
    '')
    (writeShellScriptBin "nixpkgs-update" ''
      set -e
      hash=$(
        git ls-remote --exit-code https://github.com/NixOS/nixpkgs.git \
          refs/heads/nixpkgs-unstable | cut -f1)
      sed -i "s|nixpkgs/archive/[0-9a-f]\\{40\\}|nixpkgs/archive/$hash|" shell.nix
      echo "Nixpkgs updated to $hash"
    '')
  ];

  shell' = with pkgs; ''
    export TZ=UTC
    export NIX_SSL_CERT_FILE=${cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export PYTHONNOUSERSITE=1
    export PYTHONPATH=""

    current_python=$(readlink -e .venv/bin/python || echo "")
    current_python=''${current_python%/bin/*}
    [ "$current_python" != "${python'}" ] && rm -rf .venv/

    echo "Installing Python dependencies"
    export UV_PYTHON="${python'}/bin/python"
    uv sync --frozen || exit

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
  NIX_PATH = "nixpkgs=${pkgs.path}";
  OVERPASS_API_INTERPRETER = "https://overpass.private.coffee/api/interpreter";
  PYTHONUNBUFFERED = "1";
  shellHook = shell';
}
