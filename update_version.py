import subprocess
import re
import os

def get_git_timestamp():
    """Retrieves the Unix timestamp of the last commit."""
    try:
        process = subprocess.Popen(
            ["git", "log", "-1", "--format=%ct"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        if process.returncode == 0:
            return int(stdout.decode("utf-8").strip())
        else:
            return None
    except FileNotFoundError:
        return None

def has_file_changed(file_path):
    """Checks if the given file has unstaged changes."""
    try:
        process = subprocess.Popen(
            ["git", "diff", "--quiet", "HEAD", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.communicate()
        return process.returncode != 0  # Return True if changes exist
    except FileNotFoundError:
        return True # if git is not installed, assume file has changed.

def update_version_file(version_file="batch_doc_analyzer.py"):
    """Updates the last numerical section of the VERSION constant."""

    if not has_file_changed(version_file):
        print("Version update script: No changes detected in batch_doc_analyzer.py. Skipping version update.")
        return False

    timestamp = get_git_timestamp()
    if timestamp is None:
        print("Error: Could not retrieve Git timestamp.")
        return False

    with open(version_file, "r") as f:
        lines = f.readlines()

    version_updated = False
    updated_lines = []
    for line in lines:
        if line.startswith("VERSION = "):
            match = re.search(r"^(VERSION = '.*?\.)(\d+)'$", line)
            if match:
                prefix, patch_version = match.groups()
                try:
                    current_version = int(patch_version)
                    last_timestamp = 0
                    if os.path.exists(".last_timestamp"):
                        with open(".last_timestamp", "r") as ts_file:
                            last_timestamp = int(ts_file.read().strip())

                    if timestamp >= last_timestamp: #changed from > to >=
                        new_version = current_version + 1
                        updated_lines.append(f"{prefix}{new_version}'\n")
                        version_updated = True

                        with open(".last_timestamp", "w") as ts_file:
                            ts_file.write(str(timestamp))
                    else:
                        updated_lines.append(line)
                except ValueError:
                    print("Error: Invalid version format.")
                    return False
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    if not version_updated:
        return False

    with open(version_file, "w") as f:
        f.writelines(updated_lines)

    print(f"Version updated in {version_file}")
    return True

if __name__ == "__main__":
    update_version_file()