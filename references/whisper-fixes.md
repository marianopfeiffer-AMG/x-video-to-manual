# Whisper: errores sistemáticos y cómo corregirlos

Whisper (sobre todo `base`/`small`) alucina homófonos en dominios técnicos. En charlas
sobre agentes e IA el patrón es tan consistente que se vuelve predecible.

## Errores observados

| Whisper dice | Debería decir | Contexto |
|---|---|---|
| Asian / Asians | agent / agentic / agents | **el peor**: aparece en toda charla de agentes |
| Cloud | Claude | nombre del modelo/producto |
| Cloud Managed Asians | Claude Managed Agents | producto |
| Cloud Asian SDK | Claude Agent SDK | producto |
| Cloud Code | Claude Code | producto |
| agentic furnace | agentic harness | jerga |
| MCT servers | MCP servers | protocolo |
| checkwining | checkpointing | jerga |
| entropic / Anthropik | Anthropic | empresa |
| CWC workshops | Code with Claude workshops | evento |
| grab, glob | grep, glob | herramientas |

## Cómo se corrigen

El motor (`scripts/normalize_transcript.py`) **no trae reglas hardcodeadas**: lee un TSV.

```
<patrón regex>\t<reemplazo literal>\t<nota>\t[<prioridad>]
```

- Sin `--fixes` el texto **no se modifica**. Es deliberado: no hay regla global que
  rompa texto legítimo ("Google Cloud" ≠ "Google Claude").
- Orden: prioridad (mayor = antes, default 100) y luego longitud de patrón descendente.
  La prioridad existe para poder relegar patrones que son largos en caracteres pero
  genéricos en alcance (p. ej. la regla de "Cloud" va con prioridad 10).
- El reemplazo es **literal** (no admite `\1`): para variantes, escribí más reglas.

## Cómo extenderlo

1. Corré con `--report` y mirá el `corrections.json` (original, corregido, regla, línea).
2. Buscá en la transcripción frases que "no cierran" (el hablante nunca diría eso).
3. Agregá la regla al TSV del dominio (o creá uno nuevo, p. ej. `fixes/mi-tema.tsv`).
4. Si la corrección es dudosa, marcala `[?]` en el manual en vez de forzarla.

## Mejor aún: arreglarlo en el origen

Antes de parchear, sesgá a Whisper con el vocabulario correcto. El pipeline lo deriva solo
del OCR de las slides (`scripts/build_vocab.py`) y lo pasa como `--initial_prompt`:

```bash
scripts/x-video-to-manual.sh <url> --vocab "Claude, Anthropic, MCP"   # términos extra
scripts/build_vocab.py xvm-out/slides-ocr.txt --min-count 2          # a mano, si querés
```

Reduce el error en la fuente. No lo elimina: `--initial_prompt` es una sugerencia, no una
orden, y el OCR también mete basura (por eso `--min-count 2`). Mirá `vocab.txt` y ajustá.
