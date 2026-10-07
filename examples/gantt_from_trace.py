"""Draws the Gantt chart of a recorded trace file: python gantt_from_trace.py TRACE.jsonl"""

import sys

from pydantic_squads import TerminalGantt

# Idle stretches (e.g. a cycle resumed hours later) are shortened to 2s.
TerminalGantt.from_jsonl(sys.argv[1], width=140, collapse_gaps_ms=2000).print()
