#!/usr/bin/env bash
# Pin check (REQ-112.1): reports versions that can change under us in workflow,
# manifest and MCP files. It is the interim check until u2's CI pinning lint.
#
# Usage: tools/ci/check_pins.sh PATH...
#   Each PATH is a file, or a folder searched for *.yml, *.yaml and *.json files.
#
# Each finding is printed as FILE:LINE: RULE: TEXT. The rules:
#   latest           a `latest` tag or version: image:latest, pkg@latest,
#                    version: latest, newTag: latest, runs-on: ubuntu-latest,
#                    releases/latest
#   range            a version range or wildcard: ^1.2, ~1.2, ~> 1.2, >=1.2, 1.x, *
#   action-not-sha   a GitHub Action not pinned by a full 40-character commit SHA
#   image-no-digest  a container image without an @sha256 digest
#   mcp-unversioned  an MCP server package with no version (files named *mcp*.json)
# Whole-line comments are skipped.
#
# Exit status: 0 when every reference is pinned, 1 when one is not, 2 on a usage error.
# Written for macOS bash 3.2 and BSD grep as well as Linux.
set -u

q="[\"']"                  # a single or a double quote
end='([^[:alnum:]_.-]|$)'  # what may follow a version token
version_key="[[:alnum:]_-]*([Vv]ersion|[Tt]ag|[Rr]ef)${q}?[[:space:]]*[:=][[:space:]]*${q}?"
range_op='(\^|~>?|~=|[<>]=?|!=)[[:space:]]*[0-9]'
wildcard='[0-9]+(\.[0-9]+)*\.[xX*]'

latest_re="(:|@)latest${end}"
latest_re="${latest_re}|${version_key}latest${end}"
latest_re="${latest_re}|runs-on:[[:space:]]*${q}?[[:alnum:]_.-]*-latest${end}"
latest_re="${latest_re}|releases/latest${end}"

range_re="${version_key}(${range_op}|${wildcard}|\*${q}?([[:space:],]|\$))"
range_re="${range_re}|@(${range_op}|${wildcard})"
range_re="${range_re}|[[:alpha:]][[:alnum:]_.-]*(>=|<=|~=|!=|>|<)[[:space:]]*[0-9]+\."

action_re="uses:[[:space:]]*${q}?[[:alnum:]_-][[:alnum:]_.-]*/[^[:space:]\"'#]*"
action_pinned="@[0-9a-f]{40}(${q}|[[:space:]]|\$)"

image_re="(^|[[:space:]-])(image|container):[[:space:]]*${q}?[[:alnum:]][^[:space:]\"'#]*"
image_re="${image_re}|uses:[[:space:]]*${q}?docker://[^[:space:]\"'#]*"
image_pinned='@sha256:[0-9a-f]{64}'

mcp_re="\"([[:alnum:]][[:alnum:]._-]*)?mcp[[:alnum:]._-]*\"[[:space:]]*([],]|\$)"

findings=0
files=0

# scan FILE RULE FIND_REGEX [PINNED_REGEX]
# Reports each line that matches FIND_REGEX, unless it is a whole-line comment
# or also matches PINNED_REGEX.
scan() {
  local file="$1" rule="$2" find_re="$3" pinned_re="${4:-}"
  local hit number content trimmed text
  while IFS= read -r hit; do
    number="${hit%%:*}"
    content="${hit#*:}"
    trimmed="${content#"${content%%[![:space:]]*}"}"
    case "$trimmed" in
      '#'*) continue ;;
    esac
    if [ -n "$pinned_re" ] && printf '%s\n' "$content" | grep -q -E -- "$pinned_re"; then
      continue
    fi
    text="$(printf '%s\n' "$content" | grep -o -E -- "$find_re" | head -n 1)"
    printf '%s:%s: %s: %.120s\n' "$file" "$number" "$rule" "$text"
    findings=$((findings + 1))
  done < <(grep -n -E -- "$find_re" "$file")
}

scan_file() {
  local file="$1"
  if [ ! -r "$file" ]; then
    echo "check_pins: cannot read $file" >&2
    exit 2
  fi
  files=$((files + 1))
  scan "$file" latest "$latest_re"
  scan "$file" range "$range_re"
  scan "$file" action-not-sha "$action_re" "$action_pinned"
  scan "$file" image-no-digest "$image_re" "$image_pinned"
  case "$(basename "$file")" in
    *mcp*.json) scan "$file" mcp-unversioned "$mcp_re" ;;
  esac
}

if [ "$#" -eq 0 ]; then
  echo "usage: $0 PATH..." >&2
  echo "  Each PATH is a file, or a folder searched for *.yml, *.yaml and *.json files." >&2
  exit 2
fi

for path in "$@"; do
  if [ ! -e "$path" ]; then
    echo "check_pins: no such file or folder: $path" >&2
    exit 2
  fi
done

for path in "$@"; do
  if [ -d "$path" ]; then
    while IFS= read -r file; do
      scan_file "$file"
    done < <(find "$path" \( -name .git -o -name .terraform -o -name node_modules \) -prune \
      -o -type f \( -name '*.yml' -o -name '*.yaml' -o -name '*.json' \) -print | LC_ALL=C sort)
  else
    scan_file "$path"
  fi
done

if [ "$findings" -gt 0 ]; then
  echo "check_pins: $findings unpinned reference(s) in $files file(s) (REQ-112.1)."
  exit 1
fi
echo "check_pins: every reference is pinned in $files file(s)."
