{
  description = "FHIR R4 MCP server — reproducible dev shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python312;
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.ruff
            pkgs.gnumake
          ];

          # NixOS' Python store path is read-only, so `pip install -e` can't
          # write into it. We layer a venv on top of the Nix-provided Python:
          # reproducible interpreter, mutable project install. The venv is
          # created once and reused on subsequent `nix develop` entries.
          shellHook = ''
            if [ ! -d .venv ]; then
              echo "Creating .venv with ${python.version}..."
              ${python}/bin/python -m venv .venv
            fi
            source .venv/bin/activate
            pip install -q -e ".[dev]" 2>/dev/null || \
              echo "Run 'pip install -e .[dev]' (network needed on first run)."
            echo "fhir-mcp-server dev shell ready. Try: make check"
          '';
        };
      });
}
