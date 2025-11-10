import os
from markdownify import markdownify as md

# load files in data/[env_name]/raw_data
for folder in os.listdir("data"):
    if os.path.isdir(os.path.join("data", folder)):
        for file in os.listdir(os.path.join("data", folder, "raw_data")):
            if file.endswith(".html"):
                # don't overwrite existing markdown files
                if os.path.exists(os.path.join("data", folder, "raw_data", file.replace('.html', '.md'))):
                    continue
                # load the html and convert it to markdown
                with open(os.path.join("data", folder, "raw_data", file), "r") as infile:
                    html = infile.read()
                    markdown = md(html)
                    # save the markdown to a new file in data/[env_name]/raw_data
                    with open(os.path.join("data", folder, "raw_data", file.replace('.html', '.md')), "w") as outfile:
                        outfile.write(markdown)