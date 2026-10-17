#!/bin/bash
# Vercel "Ignored Build Step" (vercel.json → ignoreCommand), used by every project built from this repo.
# Exit 0 = skip the build, exit 1 = build. When in doubt, build.
# Skips branches other than main, and main when every change since the last deployment is in docs, tools, tests,
# ad images or Markdown files.

# Work happens on branches (e.g. dev); only main deploys. Branch pushes would otherwise build a preview of every project.
if [ -n "$VERCEL_GIT_COMMIT_REF" ] && [ "$VERCEL_GIT_COMMIT_REF" != "main" ]; then
  echo "Branch $VERCEL_GIT_COMMIT_REF (not main): skipping the build."; exit 0
fi

BASE="$VERCEL_GIT_PREVIOUS_SHA"
if [ -z "$BASE" ]; then
  echo "First deployment: building."; exit 1
fi
if [ "$(git rev-parse "$BASE^{commit}" 2>/dev/null)" = "$(git rev-parse HEAD)" ]; then
  echo "Same commit as the last deployment (a redeploy): building."; exit 1
fi
if ! git cat-file -e "$BASE^{commit}" 2>/dev/null; then
  echo "Last deployed commit isn't in this checkout: building."; exit 1
fi
if git diff --quiet "$BASE" HEAD -- . \
    ':(exclude)docs' ':(exclude)tools' ':(exclude)tests' ':(exclude)static/ads' ':(exclude)ad-videos' \
    ':(exclude,glob)**/*.md'; then
  echo "Only docs, tools, tests or ad images changed since $BASE: skipping the build."; exit 0
fi
echo "App files changed since $BASE: building."; exit 1
