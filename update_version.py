import re

def update_version_from_string(version_string):
    """
    Extracts the version number from a string and increments it.

    Args:
        version_string: The string containing the VERSION constant. 
                        Supports various formats:
                        - "VERSION = 'X.Y.Z'"
                        - "VERSION = \"X.Y.Z\""
                        - "VERSION = X.Y.Z"

    Returns:
        The updated version string, or None if the version could not be extracted or incremented.
    """
    try:
        match = re.search(r"VERSION\s*=\s*['\"]?(\d+\.\d+\.)(\d+)['\"]?\s*(#.*)?$", version_string)
        if match:
            prefix = match.group(1) #get the prefix, for example 0.1.
            patch = int(match.group(2)) #get the patch number as an integer.
            new_patch = patch + 1
            new_version = f"{prefix}{new_patch}" #create the new version string
            if match.group(3):
                return f"VERSION = '{new_version}' {match.group(3)}" 
            else:
                return f"VERSION = '{new_version}'" 
        else:
            print("Error: Could not find VERSION in the string.")
            return None
    except Exception as e:
        print(f"Error: An error occurred while updating the version: {e}")
        return None

# Example Usage:
version_string = "VERSION = '0.1.1' # Last section auto-updated by make 22222212"
updated_version_string = update_version_from_string(version_string)

if updated_version_string:
    print(f"Updated version: {updated_version_string}")
else:
    print("Version update failed.")