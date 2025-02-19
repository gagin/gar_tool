import re
import sys

def update_version_in_file(version_file="batch_doc_analyzer.py"):
    """
    Reads the VERSION constant from a file, increments the patch number, and writes it back.
    Handles single quotes, double quotes, or no quotes around the version string, and preserves
    pre-patch and post-patch strings.
    """
    try:
        with open(version_file, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: File '{version_file}' not found.")
        return False

    version_updated = False
    updated_lines = []
    for line in lines:
        match = re.search(r"^((VERSION\s*=\s*['\"]?\d+\.\d+\.)(\d+)(['\"]?\s*.*))$", line)
        if match:
            pre_patch_string = match.group(2)
            patch_number = int(match.group(3))
            post_patch_string = match.group(4)
            try:
                new_patch_number = patch_number + 1
                updated_lines.append(f"'{pre_patch_string}{new_patch_number}{post_patch_string}'\n")
                version_updated = True
            except ValueError:
                print("Error: Invalid version format.")
                return False
        else:
            updated_lines.append(line)

    if not version_updated:
        print("Error: VERSION constant not found.")
        return False

    if version_updated:
        try:
            with open(version_file, "w") as f:
                f.writelines(updated_lines)
            print(f"Version updated in {version_file}")
            return True
        except IOError:
            print(f"Error: Could not write to file '{version_file}'.")
            return False
    else:
        return False

if __name__ == "__main__":
    if update_version_in_file():
        sys.exit(0)  # Exit with 0 (success) if True
    else:
        sys.exit(1)  # Exit with 1 (failure) if False