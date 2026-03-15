---
description: Hugo static site generator operations — scaffolding, building, and serving the blog site
---

# Hugo Builder

You have permission and context to run Hugo Extended commands for this project.

## Allowed operations
- `hugo new site site --format yaml` — scaffold a new site in the `/site` directory
- `hugo server` — run the dev server (from `/site`)
- `hugo` or `hugo build` — build the static site (from `/site`)
- `hugo new content posts/YYYY-MM-DD-slug.md` — create new content files

## Conventions
- The Hugo site root is `/site`
- Always `cd site` before running Hugo commands
- Site config format is YAML (`hugo.yaml`)
- Blog posts go in `site/content/posts/` with filename pattern `YYYY-MM-DD-{slug}.md`
- Hugo frontmatter uses YAML delimiters (`---`)
