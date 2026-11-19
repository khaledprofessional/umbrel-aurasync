#!/usr/bin/env bash
# Point the community app store at images published under your GitHub owner.
set -euo pipefail

owner="${1:-}"
if [[ -z "$owner" ]]; then
  echo "usage: $0 <github-owner-or-org>" >&2
  exit 1
fi

if [[ ! "$owner" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]]; then
  echo "error: '$owner' is not a valid GitHub owner/org name" >&2
  exit 1
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exports_file="$root/aura-sync/exports.sh"
manifest_file="$root/aura-sync/umbrel-app.yml"
readme_file="$root/README.md"

repo_name="umbrel-aurasync"
if git -C "$root" remote get-url origin >/dev/null 2>&1; then
  remote_url="$(git -C "$root" remote get-url origin)"
  candidate="$(basename "${remote_url%.git}")"
  if [[ -n "$candidate" && "$candidate" != "." ]]; then
    repo_name="$candidate"
  fi
fi
repo_url="https://github.com/${owner}/${repo_name}"

python3 - "$exports_file" "$manifest_file" "$readme_file" "$owner" "$repo_url" <<'PY'
import pathlib, re, sys

exports_file, manifest_file, readme_file = map(pathlib.Path, sys.argv[1:4])
owner, repo_url = sys.argv[4], sys.argv[5]

text = exports_file.read_text(encoding="utf-8")
text, count = re.subn(
    r'^export APP_AURA_SYNC_IMAGE_OWNER=.*$',
    f'export APP_AURA_SYNC_IMAGE_OWNER="{owner}"',
    text,
    flags=re.MULTILINE,
)
if count != 1:
    raise SystemExit("could not find APP_AURA_SYNC_IMAGE_OWNER in exports.sh")
exports_file.write_text(text, encoding="utf-8")

manifest = manifest_file.read_text(encoding="utf-8")
for field in ("website", "repo"):
    manifest, replacements = re.subn(
        rf'^{field}: .*$', f'{field}: {repo_url}', manifest, flags=re.MULTILINE
    )
    if replacements != 1:
        raise SystemExit(f"could not find {field} in umbrel-app.yml")
manifest, replacements = re.subn(
    r'^support: .*$',
    f'support: {repo_url}/issues',
    manifest,
    flags=re.MULTILINE,
)
if replacements != 1:
    raise SystemExit("could not find support in umbrel-app.yml")
raw_icon = repo_url.replace("https://github.com/", "https://raw.githubusercontent.com/") + "/main/aura-sync/icon.svg"
manifest, replacements = re.subn(
    r'^icon: .*$',
    f'icon: {raw_icon}',
    manifest,
    flags=re.MULTILINE,
)
if replacements != 1:
    raise SystemExit("could not find icon in umbrel-app.yml")
manifest_file.write_text(manifest, encoding="utf-8")

readme = readme_file.read_text(encoding="utf-8").replace(
    "https://github.com/yourname/umbrel-aurasync", repo_url
)
readme_file.write_text(readme, encoding="utf-8")
print(f"image owner set to {owner}")
print(f"repository metadata set to {repo_url}")
PY

echo "Next:"
echo "  1. git add -A && git commit -m 'Configure AuraSync image registry'"
echo "  2. git tag v1.0.0 && git push origin main --tags"
echo "  3. Add ${repo_url} as a community app store in umbrelOS"
