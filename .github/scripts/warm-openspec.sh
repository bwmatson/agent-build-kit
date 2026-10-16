#!/usr/bin/env bash
# Fetches the pinned OpenSpec CLI into npx's cache before the integration tests,
# with a bounded retry, and proves the binary starts. Needs GNU `timeout`.
# Usage: warm-openspec.sh <package>@<version>
set -e

spec="${1:?usage: warm-openspec.sh <package>@<version>}"
attempts=3
delay="${OPENSPEC_RETRY_DELAY:-10}"
cache="${npm_config_cache:-$HOME/.npm}"

for attempt in $(seq 1 "$attempts"); do
  echo "attempt $attempt of $attempts: npx --yes $spec --version"
  if timeout 120 npx --yes "$spec" --version; then
    exit 0
  fi
  echo "attempt $attempt failed"
  rm -rf "$cache/_npx"
  if [ "$attempt" -lt "$attempts" ]; then
    sleep $((delay * attempt))
  fi
done

echo "::error::the OpenSpec CLI is not installed: $spec could not be fetched in $attempts attempts"
exit 1
