{
  # check latest hashes at https://status.nixos.org/
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/e922e146779e250fae512da343cfb798c758509d.tar.gz") { };
  unstable = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/85306ef2470ba705c97ce72741d56e42d0264015.tar.gz") { };
}
