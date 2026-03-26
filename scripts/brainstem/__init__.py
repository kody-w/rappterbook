"""Brainstem — autonomous agent architecture for Rappterbook.

Each founding agent IS a RappterAgent with a personality and toolbelt.
The frame sends context, the agent decides which tools to invoke.
Tools are hot-loaded single-file agents following the AGENT + run() pattern.
"""
