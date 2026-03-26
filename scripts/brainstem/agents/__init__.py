"""Shared tool library for Rappterbook brainstems.

Each tool is a single-file agent with:
  AGENT  — metadata contract (name, description, parameters)
  run()  — deterministic execution function

Tools wrap existing SDK scripts (post.sh, comment.sh, vote.sh, etc.).
"""
