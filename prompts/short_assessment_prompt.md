# Moved

Ollama now uses `prompts/ollama_assessment_prompt.md`.

That prompt asks the model to produce a real structured upgrade report
grounded in the local evidence report + live inventory.
If the model returns `NN`, `0%`, or vague risks, the tool rejects it
and keeps the evidence report.
