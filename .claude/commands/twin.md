Generate content for the Rappterbook multi-platform digital twin pipeline.

## Arguments

- No args = show status + pick what to write next
- `status` = show twin pipeline stats
- `next` = auto-pick the highest priority missing content and write it
- `blog <topic>` = write a blog post on the given topic
- `podcast <topic>` = write a podcast episode script
- `x <topic>` = write an X/Twitter thread
- `newsletter <N>` = write newsletter issue N
- `substack <topic>` = write a Substack essay
- `reddit <topic>` = write a Reddit post
- `twitch <topic>` = write a Twitch stream concept
- `youtube <topic>` = write a YouTube Live concept
- `book <topic>` = write a book chapter/outline
- `guide <topic>` = write a technical guide
- `course <topic>` = write a Udemy course outline
- `prompts` = generate 5 new showcase media prompts
- `list [platform]` = list all drafts, optionally filtered
- `sync` = show cross-platform sync matrix

## Instructions

Invoke the `twin-writer` skill to handle this request. Pass the full argument string to it.

If no arguments are provided, run `python scripts/twin.py status` to show the current state, then ask what to write or auto-pick the next priority item.
