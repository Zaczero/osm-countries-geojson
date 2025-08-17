let
  # Update with `nixpkgs-update` command
  pkgs =
    import
      (fetchTarball "https://github.com/NixOS/nixpkgs/archive/32f313e49e42f715491e1ea7b306a87c16fe0388.tar.gz")
      { };

  pythonLibs = with pkgs; [
    zlib.out
    stdenv.cc.cc.lib
  ];
  python' =
    with pkgs;
    symlinkJoin {
      name = "python";
      paths = [ python313 ];
      buildInputs = [ makeWrapper ];
      postBuild = ''
        wrapProgram "$out/bin/python3.13" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath pythonLibs}"
      '';
    };

  packages' = with pkgs; [
    python'
    uv
    ruff
    curl
    jq

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
        curl -sSL \
          https://prometheus.nixos.org/api/v1/query \
          -d 'query=channel_revision{channel="nixpkgs-unstable"}' \
        | jq -r ".data.result[0].metric.revision")
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
