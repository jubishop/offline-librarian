---
name: offline-librarian
description: Answer from the offline library of medical, emergency, survival, repair and reference articles (WikEM, MedlinePlus, NHS medicines, CDC, Ready.gov, military and FEMA manuals, Wikipedia, Stack Exchange, iFixit and more) instead of from memory. Use for health, first aid, safety, emergency, how-to, repair or factual questions, especially without internet, and whenever the user asks what the library says.
---

# Offline librarian

Answer from the library, not from memory. Search it before every answer, even
when you think you know.

## Search

Run this with the question in plain words:

```sh
librarian search --json --limit 8 "QUESTION"
```

It prints the best passages as JSON, one per article: `id`, `title`,
`heading`, `source`, `url` and `text`. It searches by keyword and by meaning.

- If the passages don't answer the question, search again with other words:
  the symptom instead of the condition, a common name instead of a technical
  one, or the main noun alone. Search at most three times per question.
- To read the whole article a passage comes from, run
  `librarian read ID` with the passage's `id`. Do this when a passage is cut
  off or the details matter, such as doses, times or steps.
- For a follow-up question, search again; earlier passages may not cover it.

## Answer

- Put what to do first, in short numbered steps when there are steps. If the
  passages say to call emergency services, say that first.
- Use only facts from the passages you read. Give doses, amounts, times and
  distances exactly as the passage states them. Never invent a number.
- After each fact, name its source in brackets, like
  `[Hypothermia, WikEM emergency medicine]`.
- End with a **Sources** list: each article you used, with its source and
  its URL when it has one.
- If the passages disagree, say so and give both.

## When the library has nothing

If no search finds passages that answer the question, start with: "The library
doesn't cover this." Then give your best general answer, and label it clearly
as from memory, not from the library. Keep the safety advice conservative.

## If the command fails

- "There is no library" means it isn't built: tell the user to run
  `librarian build`.
- "Searched by keyword only" means meaning search was unavailable; keep going
  with the keyword results.
- If `librarian` isn't found, tell the user the skill's command isn't on the
  PATH: link `bin/librarian` from the Offline Librarian checkout into
  `~/.local/bin`.
