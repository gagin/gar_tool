import re

def update_version_in_file(version_file="batch_doc_analyzer.py"):
    """
    Reads the VERSION constant from a file, increments the last number, and writes it back.
    Handles single quotes, double quotes, or no quotes around the version string, and comments.
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
        match = re.search(r"^(VERSION\s*=\s*['\"]?(\d+\.\d+\.)(\d+)['\"]?\s*)(#.*)?$", line)
        if match:
            prefix = match.group(1)
            patch_version = int(match.group(3))
            comment = match.group(4)
            try:
                new_version = patch_version + 1
                if comment:
                    updated_lines.append(f"{prefix}{new_version}' {comment}\n")
                else:
                    updated_lines.append(f"{prefix}{new_version}'\n")
                version_updated = True
            except ValueError:
                print("Error: Invalid version format.")
                return False
        else:
            updated_lines.append(line)

    if not version_updated:
        print("Error: VERSION constant not found.")
        return False

    if version_updated: #added this if statement.
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
    update_version_in_file()