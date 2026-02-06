{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfreePredicate = pkg:
            builtins.elem (nixpkgs.lib.getName pkg) [ "tart" ];
        };
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.tart
            pkgs.softnet
            pkgs.sshpass
            (pkgs.python3.withPackages (ps: [
              ps.pygithub
            ]))
          ];

          shellHook = '''';
        };

        devShells.sandbox = pkgs.mkShell {
          packages = [
            pkgs.nodejs
            pkgs.gh
            pkgs.git
            (pkgs.python3.withPackages (ps: [
              ps.pygithub
            ]))
          ];
        };
      });
}
