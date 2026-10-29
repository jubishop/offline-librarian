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

It prints the best passages as JSON, one per article: `id`, `title` (the
article), `heading` (the section within it), `source`, `url` (the article's
address, sometimes empty) and `text`. It searches by keyword and by meaning.

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
- After each fact, name the passage's `title` and `source` in brackets, like
  `[Hypothermia, WikEM emergency medicine]`. Copy them from the JSON; the
  `heading` is only a section, not the article's name.
- If you add anything not in a passage, mark it `(from memory)` instead of a
  source. Never write a source you did not read.
- End with a **Sources** list: each article you cited, with its `source` and
  the `url` from that same passage, when it has one.
- On safety, follow the official and clinical sources (MedlinePlus, CDC,
  Ready.gov, FEMA, NHS, WikEM, WikiMed, the military and WHO manuals) over
  Q&A sites, wikiHow and general Wikipedia. Don't repeat exceptions that
  weaken a safety rule, such as "if you must" run an engine indoors.
- If official sources disagree, say so and give both, with their sources.

## Save each answer

After each answer, save it to the library's history, so the user can find it
again from pi or the terminal. Run this with the user's question, the `id` of
each passage you cited, and your answer exactly as you wrote it between the
`LIBRARIAN_ANSWER` lines:

```sh
librarian history add --question 'QUESTION' PASSAGE_ID PASSAGE_ID <<'LIBRARIAN_ANSWER'
YOUR ANSWER
LIBRARIAN_ANSWER
```

- Give only the ids of passages you cited; the command looks up their titles,
  sources and addresses itself. Give none when the library had nothing.
- It prints `Conversation:` and an id. For each later answer in this session,
  add `--conversation ID` with that id, so it joins the same conversation:
  `librarian history add --conversation ID --question 'QUESTION' PASSAGE_ID ...`.
- Quote the question for the shell: inside single quotes, write each `'` as
  `'\''`.
- If it says there is no passage with an id, run it again with the ids you
  cited. If it fails otherwise, tell the user the answer wasn't saved.

## Earlier conversations

When the user refers to an earlier conversation, such as "what did the library
say about burns last week", find it in the history:

```sh
librarian history search --json WORDS
librarian history show --json ID
```

`search` lists the conversations whose questions and answers hold every word,
most recent first, each with its `id`, `title` (its first question) and
`updated`. `show` prints one conversation's `turns`, each with its `question`,
`answer` and the `sources` it cited. `librarian history --json` lists the most
recent conversations.

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
