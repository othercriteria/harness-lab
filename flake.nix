{
  description = "Local Harness Lab";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachSystem [ "x86_64-linux" ] (system:
      let
        pkgs = import nixpkgs { inherit system; };
        devTools = {
          inherit (pkgs) poethepoet pre-commit ruff ty;
          inherit (pkgs.python313Packages) coverage;
        };
        pipPins = pkgs.lib.mapAttrsToList (name: tool: "${name}==${tool.version}") devTools;
      in {
        devShells.default =
          assert pkgs.lib.assertMsg
            (builtins.readFile ./requirements-dev.txt == pkgs.lib.concatLines pipPins)
            "Update requirements-dev.txt to match the locked Nix developer tools";
          pkgs.mkShell {
            packages = builtins.attrValues devTools ++ (with pkgs; [
              python313 uv nodejs git curl jq ripgrep bubblewrap
              bash coreutils diffutils findutils gnugrep gnused patch
              util-linux procps time
              opencode aider-chat
            ]);
            UV_PYTHON = "${pkgs.python313}/bin/python3.13";
            UV_PYTHON_PREFERENCE = "only-system";
            UV_PYTHON_DOWNLOADS = "never";
            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib ];
            shellHook = builtins.readFile ./scripts/environment.sh;
          };
      });
}
