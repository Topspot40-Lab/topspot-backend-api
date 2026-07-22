# TopSpot Catalogs

This directory contains source scripts, templates, and durable curation data used to generate TopSpot40 catalogs, notebooks, brochures, and printable guides.

## Directory structure

- `templates/` - reusable catalog templates
- `curation/` - hand-curated CSV decisions that should be preserved in Git
- `output/` - generated HTML, reports, images, and other reproducible output; this directory is ignored by Git

## Planned outputs

- Collections Guide
- Nostalgia Programs Guide
- Artist Spotlight Guide
- Conference Handouts
- Marketing Materials

## Workflow

Database -> Catalog Data -> HTML -> PDF

Generated output should be recreated from the source scripts and should not be committed.

## Applying collection curation

Run without `--save` to preview and validate the requested changes:

```powershell
python backend/scripts/apply_collection_curation.py `
  --csv backend/scripts/catalogs/curation/bluegrass_curation.csv
```

Add `--save` only when you intentionally want to write the curated changes to the configured database:

```powershell
python backend/scripts/apply_collection_curation.py `
  --csv backend/scripts/catalogs/curation/bluegrass_curation.csv `
  --save
```

`--save` performs database updates. Confirm the target environment and database configuration before using it.
