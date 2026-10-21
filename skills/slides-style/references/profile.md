# The Profile and the Local Assets

The title, acknowledgements and summary slides carry the same personal
details every time. They come from two places:

| What | Where | Committed? |
|---|---|---|
| Text: name line, email, website, affiliation, closing formula, fellowship sentence, which logos go where | `assets/profile.json` | yes, public |
| Files: logos, collaborator headshots, hero images | the local assets folder | **no** |

## `assets/profile.json`

```json
{
  "name": "Biprateep Dey",
  "name_line": "Biprateep Dey | বিপ্রতীপ দে",
  "email": "b.dey@utoronto.ca",
  "website": "https://biprateep.de",
  "affiliation": "University of Toronto",
  "title_logos": ["logo/uoft-statistical-sciences", "logo/cita", "logo/uoft-dunlap", "logo/vector"],
  "funder_logos": ["logo/schmidt-sciences"],
  "fellowship": "Biprateep Dey is a postdoctoral fellow at …",
  "closing": ["Thanks for your attention!", "Have questions, comments or want to collaborate?"]
}
```

The values are those of the author's most recent decks (2026). Change them
here when an affiliation or address changes; every deck after that follows.
The summary slide appends "Contact: <email>" to `closing`.

## The local assets folder

`$SLIDES_STYLE_ASSETS`, or `~/.config/slides-style/assets/` when that is
unset:

```
assets/
├── manifest.json
├── logos/      uoft-statistical-sciences.png, cita.jpeg, vector.png, …
├── people/     josh-speagle.jpeg, ting-li.jpeg, …
└── heroes/     desi-3d-map.png, stellar-stream.png, …
```

`manifest.json` maps keys to files and, for people, to the caption:

```json
{
  "logo/vector": {"file": "logos/vector.png"},
  "person/josh-speagle": {"file": "people/josh-speagle.jpeg",
    "name": "Josh Speagle", "role": "Assistant Professor",
    "institution": "University of Toronto"},
  "hero/desi-3d-map": {"file": "heroes/desi-3d-map.png",
    "alt": "DESI 3D map of galaxies, colour by redshift"}
}
```

Keys are `logo/…`, `person/…` and `hero/…`. `slidestyle.asset(key)` returns
the file, `slidestyle.person(key)` a `Person` for the acknowledgements
slide. A missing logo is skipped with a warning, so a deck still builds on a
machine without the folder; a missing person or hero raises.

The folder was first filled from the author's own decks (title and
acknowledgement slides, 2022-2026). Roles go out of date: check a person's
`role` and `institution` before a talk. Add an asset by copying the file
into the folder and adding its line to the manifest; never commit the folder
or its contents to this repository.

In Claude Slides, upload the files a deck uses as assets and place them by
the `/_blob/` url the upload returns.
