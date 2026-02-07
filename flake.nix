{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    pre-commit-hooks = {
      url = "github:cachix/pre-commit-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, flake-utils, pre-commit-hooks, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfreePredicate = pkg:
            builtins.elem (nixpkgs.lib.getName pkg) [ "tart" ];
        };
        pre-commit-check = pre-commit-hooks.lib.${system}.run {
          src = ./.;
          hooks = {
            ruff = {
              enable = true;
              name = "ruff";
              entry = "${pkgs.ruff}/bin/ruff check --fix";
              types = [ "python" ];
            };
            ruff-format = {
              enable = true;
              name = "ruff-format";
              entry = "${pkgs.ruff}/bin/ruff format";
              types = [ "python" ];
            };
          };
        };
      in
      {
        checks = {
          pre-commit = pre-commit-check;
        };

        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.tart
            pkgs.softnet
            pkgs.sshpass
            pkgs.ruff
            (pkgs.python3.withPackages (ps: [
              ps.pygithub
            ]))
          ];

          shellHook = ''
            ${pre-commit-check.shellHook}
          '';
        };

        devShells.sandbox = pkgs.mkShell {
          packages = [
            pkgs.nodejs
            pkgs.gh
            pkgs.git
            pkgs.ruff
            (pkgs.python3.withPackages (ps: [
              ps.pygithub
            ]))
          ];

          shellHook = ''
            ${pre-commit-check.shellHook}
          '';
        };
      });
}
