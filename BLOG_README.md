# Finance Blog - Python Powered

A 100% Python-powered blog for finance content. **No hand-authored HTML or JavaScript** — all HTML output is generated exclusively by Python using the `markdown` package.

Choose between:
- **Static Site Generator** (`build_site.py`) - Generates HTML files
- **Dynamic Web Server** (`blog_server.py`) - FastAPI server that renders pages on-demand

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
- `fastapi` and `uvicorn` (for dynamic server only)

## Installation

```bash
pip install -r requirements.txt
```

Or for minimal static site only:
```bash
pip install markdown
```

---

## Option 1: Static Site Generator

### Building the Site

```bash
python build_site.py
```

This generates HTML files in the `site/` directory.

### Previewing Locally

```bash
cd site
python -m http.server 8080
```

Open http://localhost:8080 in your browser.

---

## Option 2: Dynamic Web Server (Recommended for Render Web Service)

### Running Locally

```bash
uvicorn blog_server:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

### Deploying to Render as Web Service

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **New** → **Web Service**
3. Connect your GitHub repository
4. Configure:
   - **Name**: `finance-blog`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn blog_server:app --host 0.0.0.0 --port $PORT`
5. Click **Create Web Service**

The dynamic server reads Markdown files on each request, so you can update content without rebuilding.

---

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

3. For static site: Run `python build_site.py`
4. For dynamic server: Changes are immediate (just refresh the page)

## Markdown File Format

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

- Headers (`##`, `###`, etc.) — automatically included in Table of Contents
- Bold (`**text**`) and italic (`*text*`)
- Lists (ordered and unordered)
- Code blocks (inline and fenced)
- Blockquotes (`> quote`)
- Tables
- Links and images

## Project Structure

```
├── build_site.py          # Static site generator
├── blog_server.py         # Dynamic FastAPI server
├── content/               # Markdown source files
│   ├── market-outlook-2024.md
│   ├── cryptocurrency-regulation.md
│   ├── sustainable-investing-guide.md
│   ├── interest-rate-impact.md
│   └── retirement-planning-basics.md
├── site/                  # Generated HTML output (static only)
└── render.yaml            # Render deployment config
```

## Deploying to Render

### Dynamic Web Service (Recommended)

Use the included `render.yaml` or configure manually:
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn blog_server:app --host 0.0.0.0 --port $PORT`

### Static Site

- **Build Command**: `pip install markdown && python build_site.py`
- **Publish Directory**: `site`

## Design Philosophy

This project demonstrates that modern, professional websites can be built using **only Python** without writing any HTML, CSS, or JavaScript by hand. All styling is embedded in Python template strings, and all HTML is generated programmatically.

The finance theme uses a color palette inspired by professional financial services:
- **Dark blue** (`#0a1628`): Trust, stability, and authority
- **Gold** (`#f0b90b`): Prestige, value, and prosperity
- **Light gold** (`#ffd54f`): Accents and highlights

## License

MIT
