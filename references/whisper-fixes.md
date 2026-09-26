# Whisper: errores sistemáticos y correcciones

Whisper (sobre todo `base`/`small`) alucina homófonos en dominios técnicos.
Este es el diccionario vivo que usa `normalize_transcript.py`.

## Errores observados

| Whisper dice | Debería decir | Contexto |
|---|---|---|
| Asian / Asians | agent / agentic / agents | **el peor**: aparece en todo talk de agentes |
| Cloud | Claude | nombre del modelo/producto |
| Cloud Managed Asians | Claude Managed Agents | producto |
| Cloud Asian SDK | Claude Agent SDK | producto |
| Cloud Code | Claude Code | producto |
| agentic furnace | agentic harness | jerga |
| MCT servers | MCP servers | protocolo |
| checkwining | checkpointing | jerga |
| Waltz | Vault | feature |
| entropic / Anthropik | Anthropic | empresa |
| CWC workshops | Code with Claude workshops | evento |
| grab, glob | grep, glob | tools |

## Cómo extenderlo

1. Correr `normalize_transcript.py ... --report` y mirar la lista de cambios.
2. Leer el transcript buscando frases que "no cierran" (el hablante nunca diría eso).
3. Agregar la regla a `FIXES` (literal) o a `CONTEXTUAL` (requiere distinguir por contexto).
4. Nunca borrar evidencia: si una corrección es dudosa, marcarla `[?]` en el manual.

## Heurística de contexto

`Asian` a secas es ambiguo. Los patrones contextuales resuelven los casos frecuentes
(`Asian harness` → `agentic harness`, `Asian ID` → `agent ID`) y dejan `Asian` → `agent`
como último recurso. Revisar siempre esas conversiones: pueden quedar frases raras
(p. ej. `agent techniques` en lugar de `agentic techniques`).
