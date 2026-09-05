#!/bin/bash
# Put `ashland` on PATH.
set -euo pipefail
here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
dest="${1:-/usr/local/bin/ashland}"
cat > "$dest" <<SHIM
#!/usr/bin/env bash
export ASHLAND_HOME="\${ASHLAND_HOME:-$here}"
export PYTHONPATH="\$ASHLAND_HOME\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m ashland "\$@"
SHIM
chmod 755 "$dest"
mkdir -p ~/.config/ashland
conf=~/.config/ashland/ashland.conf
[ -f "$conf" ] || PYTHONPATH="$here" python3 -c \
  'from ashland.config import default_text; print(default_text(), end="")' > "$conf"
echo "installed $dest (ASHLAND_HOME=$here)"
echo "config    $conf"
