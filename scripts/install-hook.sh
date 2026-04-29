#!/usr/bin/env bash
# install-hook.sh — wire build-quality-agent into a target repo's pre-push.
#
# Idempotent: re-running just refreshes the hook. Safe to run on a repo
# that already has a pre-push hook (will warn + back up the existing one).
#
# Usage (from inside the target repo):
#   bash ~/Desktop/build-quality-agent/scripts/install-hook.sh
#
# Or explicitly point at a target:
#   bash install-hook.sh /path/to/target/repo

set -euo pipefail

AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_REPO="${1:-$(pwd)}"

if [ ! -d "$TARGET_REPO/.git" ]; then
  echo "✗ $TARGET_REPO is not a git repo" >&2
  exit 1
fi

# Make sure the package is importable. Prefer pip install -e so the hook
# is portable across machines (no hardcoded PYTHONPATH). Fall back to
# PYTHONPATH if pip install fails (e.g. PEP 668 externally-managed env).
if ! python3 -c "import build_quality_agent" 2>/dev/null; then
  echo "↳ build_quality_agent module not importable — running pip install -e ..."
  if pip install -e "$AGENT_ROOT" 2>/dev/null \
     || pip3 install -e "$AGENT_ROOT" 2>/dev/null \
     || python3 -m pip install -e "$AGENT_ROOT" 2>/dev/null \
     || python3 -m pip install --user -e "$AGENT_ROOT" 2>/dev/null \
     || python3 -m pip install --break-system-packages -e "$AGENT_ROOT" 2>/dev/null; then
    echo "↳ installed."
  else
    echo "↳ pip install failed — hook will use PYTHONPATH fallback."
  fi
fi

HOOK_PATH="$TARGET_REPO/.git/hooks/pre-push"

# Back up any existing hook so we don't lose the user's own work.
if [ -f "$HOOK_PATH" ] && [ ! -L "$HOOK_PATH" ]; then
  if ! grep -q "Auto-installed by build-quality-agent" "$HOOK_PATH" 2>/dev/null; then
    BACKUP="$HOOK_PATH.before-build-agent-$(date +%s)"
    cp "$HOOK_PATH" "$BACKUP"
    echo "↳ existing pre-push hook backed up to: $BACKUP"
  fi
fi

cat > "$HOOK_PATH" <<EOF
#!/usr/bin/env bash
# Auto-installed by build-quality-agent
# Source: https://github.com/alex-jb/build-quality-agent
# Skip with: BUILD_AGENT_SKIP=1 git push

# If the package is not pip-installed, fall back to PYTHONPATH from where
# the hook was installed. This keeps the agent working even if the user
# skipped pip install or is on a system without writable site-packages.
if ! python3 -c "import build_quality_agent" 2>/dev/null; then
  export PYTHONPATH="$AGENT_ROOT:\${PYTHONPATH:-}"
fi

exec python3 -m build_quality_agent "\$@"
EOF

chmod +x "$HOOK_PATH"

echo "✓ build-quality-agent pre-push hook installed at $HOOK_PATH"
echo ""
echo "  Test it:    cd $TARGET_REPO && git push --dry-run origin HEAD"
echo "  Skip once:  BUILD_AGENT_SKIP=1 git push"
echo "  Usage log:  python3 -m build_quality_agent --usage"
echo ""
echo "  Make sure ANTHROPIC_API_KEY is in your shell env."
