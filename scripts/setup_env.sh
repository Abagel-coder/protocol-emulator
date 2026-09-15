#!/usr/bin/env bash
# Bootstrap the local toolchain for the Tiny Tapeout / IHP SG13CMOS5L flow on macOS (Apple Silicon).
#
# Nothing is installed into the system Python. Two virtual environments are used:
#   <project>/.venv        cocotb + pytest (pinned to the template's versions) for running tests
#   $TT_TOOLS_DIR/venv     tt-support-tools requirements + LibreLane (drives OpenROAD in Docker)
# Big, self-contained tools live under $TT_TOOLS_DIR (default ~/ttsetup):
#   oss-cad-suite/         yosys, iverilog, verilator, nextpnr, sby, surfer, gtkwave
#   tt-support-tools/      Tiny Tapeout tooling, branch ihp-sg13cmos5l (symlinked as <project>/tt)
#   pdk/                   IHP-Open-PDK at the revision pinned by the GitHub GDS action
#
# Usage: scripts/setup_env.sh [--with-hardcaml] [--skip-oss-cad] [--skip-pdk] [--skip-brew]
# Re-running is safe; finished steps are skipped. Afterwards: `source env.sh` in each shell.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${TT_TOOLS_DIR:-$HOME/ttsetup}"
PY_VER="${TT_PYTHON:-3.12}"
OSS_TAG="${OSS_CAD_TAG:-2026-09-15}"
OSS_FILE="oss-cad-suite-darwin-arm64-${OSS_TAG//-/}.tgz"
LIBRELANE_VER="${LIBRELANE_VER:-3.1.0.dev3}"          # same as tt-gds-action@ihp-cmos5l
TT_TOOLS_BRANCH="ihp-sg13cmos5l"
IHP_PDK_REV="2bbec755dc67ca3db0261c3d6163e15735d66710" # pinned by tt-gds-action/install_sg13cmos5l.sh (2026-09-08)

WITH_HARDCAML=0; SKIP_OSS=0; SKIP_PDK=0; SKIP_BREW=0
for a in "$@"; do
  case "$a" in
    --with-hardcaml) WITH_HARDCAML=1 ;;
    --skip-oss-cad)  SKIP_OSS=1 ;;
    --skip-pdk)      SKIP_PDK=1 ;;
    --skip-brew)     SKIP_BREW=1 ;;
    *) echo "unknown argument: $a"; exit 2 ;;
  esac
done

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1  ($2)"; exit 1; }; }
need uv   "install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
need git  "install with: xcode-select --install"
need brew "install from https://brew.sh"

mkdir -p "$TOOLS"

if [ "$SKIP_BREW" = 0 ]; then
  log "1/6 Homebrew libraries used by tt-support-tools' PNG/SVG rendering (libpng, qhull, cairo)"
  if ! brew list --versions libpng qhull cairo >/dev/null 2>&1; then
    # Non-fatal: these are only needed for tt_tool.py --create-png/--create-svg, not for tests or hardening.
    brew install libpng qhull cairo || echo "WARNING: brew install failed (check permissions on \$(brew --prefix)); continuing without PNG rendering support"
  fi
else
  log "1/6 Homebrew step skipped"
fi

log "2/6 Project venv: $ROOT/.venv (pytest + project tooling; cocotb lives in the OSS CAD Suite Python)"
[ -d "$ROOT/.venv" ] || uv venv --python "$PY_VER" "$ROOT/.venv"
uv pip install --python "$ROOT/.venv/bin/python" pytest==8.4.2

log "3/6 tt-support-tools ($TT_TOOLS_BRANCH) + LibreLane venv: $TOOLS/venv"
if [ -d "$TOOLS/tt-support-tools/.git" ]; then
  git -C "$TOOLS/tt-support-tools" pull -q --ff-only || true
else
  git clone -q -b "$TT_TOOLS_BRANCH" https://github.com/TinyTapeout/tt-support-tools "$TOOLS/tt-support-tools"
fi
[ -d "$TOOLS/venv" ] || uv venv --python "$PY_VER" "$TOOLS/venv"
uv pip install --python "$TOOLS/venv/bin/python" -r "$TOOLS/tt-support-tools/requirements.txt" "librelane==$LIBRELANE_VER"
[ -e "$ROOT/tt" ] || ln -s "$TOOLS/tt-support-tools" "$ROOT/tt"   # the template's docs expect ./tt/tt_tool.py

if [ "$SKIP_OSS" = 0 ]; then
  log "4/6 OSS CAD Suite $OSS_TAG -> $TOOLS/oss-cad-suite (about 520 MB download)"
  if [ ! -x "$TOOLS/oss-cad-suite/bin/yosys" ]; then
    curl -L --progress-bar -o "$TOOLS/$OSS_FILE" \
      "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/$OSS_TAG/$OSS_FILE"
    tar -xzf "$TOOLS/$OSS_FILE" -C "$TOOLS"
    xattr -dr com.apple.quarantine "$TOOLS/oss-cad-suite" 2>/dev/null || true
    rm -f "$TOOLS/$OSS_FILE"
  fi
  # The suite's simulators embed the suite's bundled Python, so cocotb must live there too.
  # Pin it to the version the GitHub test workflow uses (test/requirements.txt).
  "$TOOLS/oss-cad-suite/bin/tabbypip" install -q cocotb==2.0.1 pytest==8.4.2
  # pip writes console scripts with a shebang pointing at bin/tabbypy3, which is itself a bash
  # script, so the kernel cannot use it as an interpreter. Restore a suite-style wrapper.
  cat > "$TOOLS/oss-cad-suite/bin/cocotb-config" <<'WRAP'
#!/usr/bin/env bash
release_bindir="$(dirname "${BASH_SOURCE[0]}")"
release_bindir_abs="$("$release_bindir"/../libexec/realpath "$release_bindir/../bin")"
release_topdir_abs="$("$release_bindir"/../libexec/realpath "$release_bindir/..")"
export PATH="$release_bindir_abs:$PATH"
export PYTHONEXECUTABLE="$release_bindir_abs/tabbypy3"
exec $release_bindir_abs/tabbypy3 -c 'import sys; from cocotb_tools.config import main; sys.argv[0] = "cocotb-config"; sys.exit(main())' "$@"
WRAP
  chmod +x "$TOOLS/oss-cad-suite/bin/cocotb-config"
else
  log "4/6 OSS CAD Suite skipped"
fi

if [ "$SKIP_PDK" = 0 ]; then
  log "5/6 IHP PDK (pinned revision) -> $TOOLS/pdk"
  PDK_ROOT="$TOOLS/pdk"
  if [ ! -f "$PDK_ROOT/ihp-sg13cmos5l/SOURCES" ]; then
    mkdir -p "$PDK_ROOT"
    git -C "$PDK_ROOT" init -q
    git -C "$PDK_ROOT" fetch -q --depth 1 https://github.com/IHP-GmbH/IHP-Open-PDK.git "$IHP_PDK_REV"
    git -C "$PDK_ROOT" checkout -q FETCH_HEAD
    echo "IHP-Open-PDK $IHP_PDK_REV" > "$PDK_ROOT/ihp-sg13cmos5l/SOURCES"
  fi
else
  log "5/6 PDK skipped"
fi

if [ "$WITH_HARDCAML" = 1 ]; then
  log "6/6 Hardcaml via opam (switch 'hardcaml', OCaml 5.3.0)"
  command -v opam >/dev/null 2>&1 || brew install opam
  [ -d "$HOME/.opam" ] || opam init -y --bare
  opam switch list -s 2>/dev/null | grep -qx hardcaml || opam switch create hardcaml 5.3.0 -y
  eval "$(opam env --switch=hardcaml --set-switch)"
  opam install -y dune core utop hardcaml ppx_hardcaml hardcaml_waveterm hardcaml_verilator
else
  log "6/6 Hardcaml skipped (re-run with --with-hardcaml to install opam + Hardcaml)"
fi

cat > "$ROOT/env.sh" <<ENV
# Generated by scripts/setup_env.sh on $(date +%F). Source this in every shell: source env.sh
export TT_TOOLS_DIR="$TOOLS"
export PDK_ROOT="$TOOLS/pdk"
export PDK=ihp-sg13cmos5l
export LIBRELANE_TAG="$LIBRELANE_VER"
export PATH="\$TT_TOOLS_DIR/venv/bin:\$PATH"             # librelane (tt-support-tools venv)
source "$ROOT/.venv/bin/activate"                       # project venv: python -> .venv (assembler, generators)
# OSS CAD Suite goes LAST so its bin is first on PATH: its simulators embed the suite's own
# Python, so cocotb-config/cocotb must be the suite's copy (pinned to the CI version below).
[ -f "\$TT_TOOLS_DIR/oss-cad-suite/environment" ] && source "\$TT_TOOLS_DIR/oss-cad-suite/environment"
export PATH="$ROOT/.venv/bin:\$PATH"                    # keep python/pytest -> project venv
export COCOTB_CONFIG="\$TT_TOOLS_DIR/oss-cad-suite/bin/cocotb-config"
# tt_tool.py imports cairosvg, which dlopens libcairo; the suite bundles an arm64 copy, so no Homebrew needed.
export DYLD_FALLBACK_LIBRARY_PATH="\$TT_TOOLS_DIR/oss-cad-suite/lib\${DYLD_FALLBACK_LIBRARY_PATH:+:\$DYLD_FALLBACK_LIBRARY_PATH}"
tt_tool() { "\$TT_TOOLS_DIR/venv/bin/python" "\$TT_TOOLS_DIR/tt-support-tools/tt_tool.py" --ihp "\$@"; }
tt_fpga() { "\$TT_TOOLS_DIR/venv/bin/python" "\$TT_TOOLS_DIR/tt-support-tools/tt_fpga.py" "\$@"; }
if command -v opam >/dev/null 2>&1 && [ -d "\$HOME/.opam/hardcaml" ]; then eval "\$(opam env --switch=hardcaml --set-switch)"; fi
true
ENV

log "Done."
cat <<MSG

Next steps:
  source env.sh
  yosys -V && iverilog -V | head -1 && sby --help >/dev/null && echo "HDL tools OK"
  open -a Docker            # LibreLane hardening runs OpenROAD in Docker; give it >= 10 GB RAM
  cd test && make -B        # once the template's src/ and test/ are in this repo
  tt_tool --create-user-config && tt_tool --harden && tt_tool --print-stats
MSG
