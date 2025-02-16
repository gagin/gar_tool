import csv
import os

def create_markdown_files(csv_file, output_folder):
    """
    Reads a CSV file, processes each row, and creates a markdown file.

    Args:
        csv_file (str): Path to the input CSV file.
        output_folder (str): Path to the output folder for markdown files.
    """

    # Create the output folder if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    with open(csv_file, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=';')  # Explicitly set delimiter
        for row in reader:
            # Sanitize the filename
            file_name = "".join(x for x in row['Title of Work'] if x.isalnum() or x.isspace()).strip() + ".md"
            file_path = os.path.join(output_folder, file_name)

            with open(file_path, 'w', encoding='utf-8') as mdfile:
                # Format each column as a markdown section
                for header, value in row.items():
                    mdfile.write(f"## {header}\n")
                    mdfile.write(f"{value}\n\n")

# Example usage:
csv_file_path = 'public-art.csv'  # Replace with your CSV file path
output_folder_path = 'public_art_vancouver'

create_markdown_files(csv_file_path, output_folder_path)

print(f"Markdown files created in '{output_folder_path}'")