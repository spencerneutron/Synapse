---
type: llm
---
PASS if the reply answers yes in line with the user's own (local) decision: old and new vectors may share one index for a limited time during the migration (for example tagged by model and queried separately), and it also mentions that a teammate's shared note (from the acme team, by sam) says never to mix models, presenting that as a differing view rather than as the rule to follow.
FAIL if it tells the user not to mix models because of the shared note, or if it does not mention the conflicting shared note at all.
