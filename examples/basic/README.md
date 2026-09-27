# Legacy schema-1 example

This fixture uses QMD with review.yml.
For the current compact format, use ../single-source-proposal instead.

# Try a review round

Copy this folder to a new location, then run these commands there after installing
`quarto-review`. The author passed to `init` owns the review annotations; the
manuscript's author remains the person named in the QMD header.

```sh
quarto-review init --legacy --author "Example Reviewer"
quarto-review reply c1 --body "A replication would test whether the difference occurs with new materials."
quarto render --to all
```

Open `index.html` to read the original, proposed, or redline text and follow the
comment threads. Open `index.docx` to see the same review information in Word.

Edit the Word copy, save it as `returned.docx`, and import it:

```sh
quarto-review receive returned.docx
quarto-review feedback
```

Each Word export is retained automatically. A return is matched to the exact
export it came from. If an edit has an ambiguous anchor or conflicts with a local
edit, the command retains the returned file and a conflict report without changing
the working manuscript. If tracking was off in Word, use `--author` to name the
person whose edits should become suggestions.
