# Finance Blog Static Site Generator

A 100% Python-powered static site generator for a finance-themed blog. **No hand-authored HTML or JavaScript** — all HTML output is generated exclusively by Python using the `markdown` package.

## Features

- **Pure Python**: All processing and HTML generation is done in Python
- **Markdown-based content**: Write blog posts in simple Markdown format
- **Automatic metadata extraction**: Title, date, and author are parsed from each post
- **Professional finance theme**: Dark blue background with gold/yellow accents
- **Table of Contents**: Automatically generated for each article
- **Responsive design**: Works on desktop and mobile devices
- **Navigation**: Home link and article-to-article navigation

## Requirements

- Python 3.8+
- `markdown` package

## Installation

```bash
pip install markdown
```

## Usage

### Building the Site

Run the build script from the repository root:

```bash
python build_site.py
```

This will:
1. Read all Markdown files from the `content/` directory
2. Extract metadata (title, date, author) from each file
3. Convert Markdown content to HTML
4. Generate `index.html` with a list of all posts
5. Generate individual HTML pages for each article
6. Output all files to the `site/` directory

### Previewing the Site

After building, you can preview the site locally:

```bash
cd site
python -m http.server 8080
```

Then open http://localhost:8080 in your browser.

## Adding New Articles

1. Create a new Markdown file in the `content/` directory (e.g., `content/my-new-post.md`)

2. Add the required metadata at the top of the file:

```markdown
# Your Article Title
date: 2024-04-01
author: Your Name

Your article content starts here...

## Section Heading

More content...
```

3. Run the build script:

```bash
python build_site.py
```

4. Your new article will appear on the homepage and have its own page at `site/my-new-post.html`

## Markdown File Format

Each Markdown file must start with the following format:

```markdown
# Post Title
date: YYYY-MM-DD
author: Author Name

Content starts after the empty line...
```

- **Line 1**: Title as a Markdown heading (`# Title`)
- **Line 2**: Date in `YYYY-MM-DD` format
- **Line 3**: Author name
- **Line 4**: Empty line (separates metadata from content)
- **Line 5+**: Article content in Markdown

### Supported Markdown Features

The generator supports standard Markdown plus:

- Headers (`##`, `###`, etc.) — automatically included in Table of Contents
- Bold (`**text**`) and italic (`*text*`)
- Lists (ordered and unordered)
- Code blocks (inline and fenced)
- Blockquotes (`> quote`)
- Tables
- Links and images

## Project Structure

```
├── build_site.py          # Python static site generator
├── content/               # Markdown source files
│   ├── market-outlook-2024.md
│   ├── cryptocurrency-regulation.md
│   ├── sustainable-investing-guide.md
│   ├── interest-rate-impact.md
│   └── retirement-planning-basics.md
└── site/                  # Generated HTML output (gitignored)
    ├── index.html
    └── [article-slug].html
```

## Deploying to Render

You can deploy the static site to [Render](https://render.com) as a Static Site:

### Option 1: Using Render Dashboard

1. **Build the site locally first**:
   ```bash
   python build_site.py
   ```

2. **Push the `site/` folder to your repository** (temporarily remove it from `.gitignore` or use a separate branch)

3. **Create a new Static Site on Render**:
   - Go to [Render Dashboard](https://dashboard.render.com)
   - Click **New** → **Static Site**
   - Connect your GitHub repository
   - Configure:
     - **Name**: `finance-blog` (or your preferred name)
     - **Branch**: `main` (or your branch)
     - **Publish Directory**: `site`
   - Click **Create Static Site**

### Option 2: Using Build Command on Render

1. **Create a new Static Site on Render**:
   - Go to [Render Dashboard](https://dashboard.render.com)
   - Click **New** → **Static Site**
   - Connect your GitHub repository

2. **Configure build settings**:
   - **Name**: `finance-blog`
   - **Branch**: `main`
   - **Build Command**: `pip install markdown && python build_site.py`
   - **Publish Directory**: `site`

3. Click **Create Static Site**

Render will automatically rebuild and deploy your site whenever you push changes to the repository.

### Option 3: Using render.yaml

Create a `render.yaml` file in your repository root:

```yaml
services:
  - type: web
    name: finance-blog
    env: static
    buildCommand: pip install markdown && python build_site.py
    staticPublishPath: ./site
```

Then connect your repository to Render, and it will automatically detect the configuration.

### Starting the Deployed Site

Once deployed, Render provides a URL like `https://finance-blog.onrender.com` where your site will be live. The site starts automatically—no manual start command is needed for static sites on Render.

## Design Philosophy

This project demonstrates that modern, professional websites can be built using **only Python** without writing any HTML, CSS, or JavaScript by hand. All styling is embedded in Python template strings, and all HTML is generated programmatically.

The finance theme uses a color palette inspired by professional financial services:
- **Dark blue** (`#0a1628`): Trust, stability, and authority
- **Gold** (`#f0b90b`): Prestige, value, and prosperity
- **Light gold** (`#ffd54f`): Accents and highlights

## License

MIT
