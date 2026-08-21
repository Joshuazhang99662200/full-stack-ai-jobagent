# Optimizer failure handling

Use typed failures for missing evidence, evidence conflict, invalid provider output, unsupported claim, unsupported metric, semantic exaggeration, contradiction, context limits, render validation, and human review requirements.

Attempt structured-output repair once. Retry only provider-declared transient transport failures. Never retry evidence or policy failures with looser instructions.
