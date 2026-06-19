# evaluate_progress

USE WHEN: At reflection checkpoints, to honestly assess whether the agent is on track.

## TEMPLATE

GOAL: {goal}

PROGRESS SNAPSHOT:
- Step: {step}/{max_steps}
- Elapsed: {elapsed_min:.0f}/{max_min:.0f} min
- Memory chunks: {n_chunks} from {n_sources} sources
- Output sections written: {sections}
- Recent actions:
{recent_actions}

Score progress on a 0-10 scale for each dimension:
- coverage: Have we covered the scope?
- depth: Are findings deep enough or just superficial?
- writing: Is the output document actually being produced?
- efficiency: Are we wasting steps on duplicate searches or failed tools?

Return JSON with:
- "scores": object with coverage, depth, writing, efficiency (0-10 ints)
- "verdict": one of "on_track", "behind", "should_pivot"
- "next_focus": list of 2-4 short strings naming what to do next
- "should_start_writing": bool — true if it's time to produce output sections
- "should_stop": bool — true if goal is essentially complete

Return ONLY valid JSON.
