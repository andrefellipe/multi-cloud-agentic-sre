"""Fail the PR check unless the description fills in the methodology fields.

Reads the PR body from the PR_BODY environment variable (set by the workflow),
so the body is never interpolated into a shell command.
"""
import os
import re
import sys

body = os.environ.get("PR_BODY") or ""
text = re.sub(r"<!--.*?-->", "", body, flags=re.S)


def field(label):
    match = re.search(rf"^[ \t]*(?:-[ \t]*)?{re.escape(label)}[ \t]*(.*)$", text, flags=re.M)
    return match.group(1).strip() if match else None


errors = []
if "## AI involvement" not in text:
    errors.append("Missing the '## AI involvement' section.")
for label in ("AI wrote:", "I changed or rejected:"):
    value = field(label)
    if value is None:
        errors.append(f"Missing '{label}' in the AI involvement section.")
    elif len(value) < 3:
        errors.append(f"'{label}' is empty. Write 'nothing' if that's the honest answer.")

requirements = field("Requirements:")
if requirements is None or not (
    re.search(r"REQ-\d{3}", requirements) or requirements.lower() in ("n/a", "none")
):
    errors.append("'Requirements:' must list requirement IDs (REQ-001) or say n/a.")

if errors:
    print("PR description check failed:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
print("PR description check passed.")
