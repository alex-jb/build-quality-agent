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

HOOK_PATH="$TARGET_REPO/.git/hooks/pre-push"

# Back up any existing hook so we don't lose the user's own work.
if [ -f "$HOOK_PATH" ] && [ ! -L "$HOOK_PATH" ]; then
  BACKUP="$HOOK_PATH.before-build-agent-$(date +%s)"
  cp "$HOOK_PATH" "$BACKUP"
  echo "↳ existing pre-push hook backed up to: $BACKUP"
fi

cat > "$HOOK_PATH" <<EOF
#!/usr/bin/env bash
# Auto-installed by build-quality-agent — see $AGENT_ROOT
# Skip with: BUILD_AGENT_SKIP=1 git push
exec python3 -m build_quality_agent "\$@" < /dev/null
EOF

chmod +x "$HOOK_PATH"

# Make sure the package is on PYTHONPATH for both the user's shell and the
# hook. We don't pip install here — keeping deps zero. The hook adds the
# agent root to PYTHONPATH at runtime via .git/hooks/pre-push wrapper.
sed -i.bak "1a\\
export PYTHONPATH=\"$AGENT_ROOT:\${PYTHONPATH:-}\"
" "$HOOK_PATH"
rm -f "$HOOK_PATH.bak"

echo "✓ build-quality-agent pre-push hook installed at $HOOK_PATH"
echo ""
echo "  Test it:    cd $TARGET_REPO && git push --dry-run origin HEAD"
echo "  Skip once:  BUILD_AGENT_SKIP=1 git push"
echo ""
echo "  Make sure ANTHROPIC_API_KEY is in your shell env or repo .env."
