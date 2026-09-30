# Auditoría — skill x-video-to-manual (Lango / OpenClaw) — skill completa: repo + copia instalada + corridas reales — 2026-09-29 20:55 ART

## Veredicto

La skill está bien construida para lo que dice ser (charlas con slides) y el repo tiene una base de ingeniería razonable (tests, CI, caché de etapas, correcciones opt-in). El problema principal es operativo, no de código: **producción corre una copia desfasada del repo** (sin caché, sin agrupado visual, con el diccionario viejo), y **el pipeline no tiene ningún límite de recursos** (threads = todos los cores, sin `nice`, sin tope de modelo/duración, sin lock de concurrencia) en un VPS de 2 vCPU / 3,8 GB que ya se cayó por procesos pesados y que sostiene 6 agentes. Además, el uso real son screencasts, no slides: ahí la abstracción "slide" degenera (34 slides de 38 frames), el vocabulario que prima a Whisper es basura de UI, y el diccionario de correcciones aplicó **0 reglas en las 2 corridas** analizadas.

## Alcance revisado

- **Tipo de proyecto:** skill de agente LLM (OpenClaw) = `SKILL.md` + scripts bash/Python + diccionario + template. Sin base de datos, sin endpoints, sin dinero. Checks aplicados: trabajo vs intención, secretos, verificabilidad (tests/CI), scripts/CLI (fallos a mitad, rutas, comandos), skills/prompts (instrucciones al agente, referencias inexistentes), documentación vs código, recursos en host compartido.
- **Fuente principal:** clon del repo público `marianopfeiffer-AMG/x-video-to-manual`, HEAD `5918223`, 12 commits (2026-09-26 20:36 → 2026-09-27 02:52 UTC). Leído completo: `SKILL.md`, `README.md`, los 7 scripts, `references/`, `templates/`, los 5 archivos de `tests/`, `.github/workflows/ci.yml`, `.gitignore`, `requirements-dev.txt`, `examples/` (cabecera).
- **Copia instalada en el VPS** (`workspace/skills/x-video-to-manual/`): comparada con `diff -rq` contra el repo. Difieren `SKILL.md`, `anthropic-agents.tsv`, `align_slides.py`, `build_vocab.py`, `x-video-to-manual.sh`; falta `stages.py`; sobran `corrections.json` y `manual-draft.md` (151 KB).
- **Evidencia de uso real** (`muestras/`): corrida 2026-09-28 "fable" (mp4 local, 12,7 min, **versión repo**: tiene `.stages.json` y el timeline dice "agrupadas por imagen") y corrida 2026-09-29 "heyfredds" (X, 17,7 min, **versión instalada/desfasada**: `chain-heyfredds.sh:8` invoca `skills/x-video-to-manual/…` y el timeline no indica modo de agrupado). Más `chain-heyfredds.sh`, los dos logs e `inventario-salidas.txt`.
- **Quedó afuera:** no tengo SSH al VPS (no pude ver permisos reales, usuario del gateway, uso de disco, las 3 propuestas del skill-workshop ni el clon `workspace/repos/`). No corrí tests, linters ni scripts (no autorizados). No vi video/audio/frames de las corridas.

## Hallazgos

### [ALTO] El pipeline no tiene ningún límite de recursos ni de concurrencia en un host compartido chico
- Dónde: `scripts/x-video-to-manual.sh:79` (`NPROC` = todos los cores), `:259-263` (`whisper … --threads "$NPROC"`, sin `nice`/`ionice`), `:122-123` (yt-dlp sin `--max-filesize`, sin `--match-filter duration`, sin `--no-playlist`, sin timeout), `:19,53` (`--model` sin validar). Uso real: `muestras/chain-heyfredds.sh:5-6`.
- Evidencia: el agente tuvo que serializar a mano tres videos con bucles `while pgrep -f "whisper .*audio.wav"; do sleep 20; done` porque el script no impide corridas simultáneas. Whisper `small` en CPU ocupa ~2 GB de RAM; `medium`/`large` necesitan 5–10 GB y el host tiene 3,8 GB; nada impide que el agente pase `--model medium` o un link a un video de 2 h (yt-dlp acepta cualquier URL soportada, no solo X). La corrida heyfredds ocupó los 2 cores durante ~50 min (log: `fetched_utc=14:08:37Z` → `chain3 done 15:02:00Z`).
- Impacto: OOM o starvation del gateway de OpenClaw → caen los 6 agentes de producción (ya pasó en este host por procesos pesados). Un video largo o un modelo grande lo dispara con un solo mensaje de chat.
- Recomendación: (1) `nice -n 19 ionice -c3` en whisper/ffmpeg/tesseract; (2) `--threads $((NPROC-1))` como mínimo 1; (3) lock (`flock /tmp/xvm.lock`) para una sola corrida a la vez; (4) whitelist de modelos (`tiny|base|small`) o chequeo de RAM libre; (5) leer la duración con ffprobe antes de whisper y abortar por encima de un tope (p. ej. 45 min) salvo `--allow-long`; (6) yt-dlp con `--no-playlist --max-filesize 1G --socket-timeout 30`; (7) `systemd-run --scope -p MemoryMax=2G` si el host es systemd. Documentar todo esto en `SKILL.md` para que el agente no improvise.
- Cómo verificar el arreglo: lanzar dos corridas simultáneas → la segunda debe esperar o fallar con mensaje; `--model large` debe ser rechazado; `top` durante whisper debe mostrar `NI 19` y `free -m` > 1 GB libre.

### [ALTO] Producción ejecuta una versión desfasada de la skill; los tests y el CI no cubren lo que corre
- Dónde: `workspace/skills/x-video-to-manual/` (lo que OpenClaw carga como `ready`) vs repo HEAD `5918223`. `muestras/chain-heyfredds.sh:8`.
- Evidencia: `diff -rq` → difieren 5 archivos, falta `scripts/stages.py` (commit `907f777`), TSV con 20 reglas vs 24, `build_vocab.py` sin el filtro de concatenaciones (`41c7b8e`), `align_slides.py` sin agrupado visual (`d4f0774`), `.sh` sin caché ni upscale de OCR. La corrida del 29/09 salió de esa copia: su `timeline.md:3` dice "51 slides, 51 tramos" sin "(slides agrupadas por imagen)", y no hay `.stages.json` en su kit (`inventario-salidas.txt:9`). Al mismo tiempo el repo al día está clonado en `workspace/repos/x-video-to-manual/`, que OpenClaw no lee.
- Impacto: cinco commits de arreglos (reanudación, agrupado visual, filtro de vocabulario, 4 reglas nuevas) nunca llegaron al agente; si Whisper hubiese muerto en la corrida heyfredds se perdía todo. Cualquier bug que se arregle en el repo seguirá vivo en prod.
- Recomendación: hacer que `workspace/skills/x-video-to-manual` sea un symlink al clon del repo (o un `git pull` en un paso de deploy documentado) y borrar los artefactos ajenos (`corrections.json`, `manual-draft.md`). Revisar y descartar/mergear las 3 propuestas del skill-workshop para que no haya una cuarta versión.
- Cómo verificar el arreglo: en el VPS `diff -rq workspace/skills/x-video-to-manual workspace/repos/x-video-to-manual -x .git -x docs` → sin salida; `openclaw --profile prod skills list` sigue mostrando la skill `ready`; el próximo kit tiene `.stages.json`.

### [ALTO] El orden de prioridad del vocabulario está invertido respecto de cómo trunca Whisper
- Dónde: `scripts/build_vocab.py:97-102` (mejores candidatos primero, `--extra` del usuario "van primero"), `:108-112` (corta a 900 chars por el final), `:122-123` (ayuda: "Whisper lo trunca cerca de los 224 tokens").
- Evidencia: openai-whisper conserva **los últimos** `n_ctx/2 - 1 = 223` tokens del `initial_prompt` (`decoding.py`, `prompt_tokens[-(n_ctx//2 - 1):]`). El `vocab.txt` de heyfredds tiene 895 chars y 83 términos con guiones bajos y CamelCase (`EMA_9_21_Cross_v2`, `Mean_Reversion_v`, `PRODUCTION-SCRI`…), que tokenizan caro; es muy probable que supere los 223 tokens. En ese caso lo que se descarta es el **principio** de la lista: justo los `--vocab` del usuario y los términos mejor rankeados, y lo que llega a Whisper es la cola (los peores candidatos).
- Impacto: la pieza central del diseño ("arreglarlo en el origen") funciona al revés cuando el OCR es abundante, que es siempre en screencasts. Explica en parte que Whisper siguiera diciendo "Claudia", "cloud", "hoddle beta" pese al vocabulario.
- Recomendación: medir tokens con el tokenizer de Whisper (tiktoken `gpt2`/multilingual) y cortar a ≤ 200 tokens, no a 900 chars; o invertir el orden de salida para que lo importante quede al final; bajar `max_chars` a ~500 como parche inmediato.
- Cómo verificar el arreglo: `python3 -c "import tiktoken;e=tiktoken.get_encoding('gpt2');print(len(e.encode(' '+open('vocab.txt').read().strip())))"` sobre el `vocab.txt` de heyfredds → hoy esperado > 223; tras el arreglo ≤ 200. Test unitario que falle si `', '.join(terms)` supera el presupuesto en tokens.

### [MEDIO] Diseñado para slides, usado para screencasts: la abstracción "slide" y el vocabulario degeneran
- Dónde: `scripts/align_slides.py:130-153` (agrupado visual, umbral 0,08), `scripts/build_vocab.py:78-98`, `README.md:162-164` ("los términos reales se repiten entre slides").
- Evidencia: corrida fable (versión repo, agrupado por imagen): 38 frames → **34 slides** (`timeline.md:3`); corrida heyfredds (por texto): 89 → 51. En un screencast cada frame difiere del anterior (scroll, cursor, ventanas), así que cada frame es una "slide" y el timeline es la transcripción cortada cada N segundos con 176 KB de OCR de UI pegado (`slides-ocr.txt` de heyfredds: 3.775 líneas, 639 de menos de 8 caracteres). El `vocab.txt` de fable es chrome de navegador: `GWJOttwiXHO7IWAIP, GWJOttwIXHO7IWAIP, Bookmarks, Chrome, Window, Download, Search, Upload, History…` — pasó el filtro de `41c7b8e` porque tiene mayúsculas internas, y `--min-count 2` no filtra nada porque la UI se repite en todos los frames (el supuesto del README es el inverso en screencasts).
- Impacto: el prompt de Whisper se llena de ruido, el timeline pesa 111 KB sin aportar estructura, y el agente termina redactando desde la transcripción cruda (ver hallazgo del borrador).
- Recomendación: detectar el modo (si slides/frames > 0,6 → screencast) y en ese caso: subir `--frames-every`, no derivar vocabulario automático (o hacerlo con una stoplist de UI: Chrome, Bookmarks, File, Edit, View…), y agrupar por ventana de tiempo. Documentar en `SKILL.md` que para tutoriales de pantalla conviene `--no-auto-vocab --vocab "<términos del post>"`.
- Cómo verificar el arreglo: sobre el kit fable, `align_slides.py` debería dar < 15 slides y `vocab.txt` no debería contener `Chrome|Bookmarks|Window|Download`.

### [MEDIO] El diccionario de correcciones es de un solo dominio, está hardcodeado en la doc, y aplicó 0 reglas en las 2 corridas
- Dónde: `SKILL.md:65-66, 89` (siempre `references/fixes/anthropic-agents.tsv`), `references/fixes/anthropic-agents.tsv:20,30` (reglas sensibles a mayúsculas: `Cloud Code`, `\bCloud\b`), `references/whisper-fixes.md:37-42`.
- Evidencia: `corrections.json` de heyfredds → `"rule_count": 20, "corrections": []`; `transcript.txt` y `transcript.clean.txt` son byte a byte idénticos en las dos corridas (`cmp`). En heyfredds quedaron sin corregir `cloud` ×4 (líneas 279, 292, 329, 371 de `transcript.clean.txt`), `cloud code` (334), `Claudia` (115), `hoddle beta` (124-125), `whip swords` (178), `12-ally` (47). El manual fable lo dice explícitamente (`MANUAL-FINAL.md`, Apéndice A: "El diccionario … no aplicó ninguna regla (0 correcciones)") y lista 11 correcciones hechas a mano que nunca volvieron a un TSV.
- Impacto: el paso 2 del pipeline es un no-op fuera de charlas de Anthropic; el conocimiento que el agente genera corrigiendo a mano se pierde en cada corrida.
- Recomendación: `(?i)` en las reglas de `Cloud`/`Cloud Code` (con el mismo lookbehind), y en `SKILL.md` instruir al agente a crear `references/fixes/<tema>.tsv` (o `<kit>/fixes.tsv`) con las correcciones que detecta, y a correr `normalize_transcript.py` con ese archivo antes de redactar. Un test que compruebe que `cloud code` → `Claude Code`.
- Cómo verificar el arreglo: `normalize_transcript.py transcript.txt --fixes … --report` sobre el kit heyfredds → `corrections` > 0 y `transcript.clean.txt` ≠ `transcript.txt`.

### [MEDIO] Defaults relativos al cwd + rutas relativas en la doc ensucian el directorio de la skill (reproducido en producción)
- Dónde: `scripts/normalize_transcript.py:89-90` (`--report` sin valor → `corrections.json` en el cwd), `scripts/build_manual.py:68` (`--out` default `manual-draft.md` en el cwd), `SKILL.md:65-66, 89` (`--fixes references/fixes/anthropic-agents.tsv`, ruta relativa que obliga a pararse en el directorio de la skill). `.gitignore` no cubre ninguno de los dos archivos.
- Evidencia: la copia instalada contiene `corrections.json` (`"input": "/opt/openclaw-prod/agentes/lango/workspace/xvm/heyfredds-…/transcript.txt"`, `"fixes": ["references/fixes/anthropic-agents.tsv"]` → cwd era la skill) y `manual-draft.md` de 151.800 bytes, ambos del 29/09.
- Impacto: cada corrida pisa los archivos de la anterior dentro de la skill; si el agente se para en la raíz del workspace, los deja ahí (y en este stack, muchos `.md` en la raíz del workspace revientan el system prompt de OpenClaw). En el repo, correr el Quickstart deja archivos sin ignorar listos para commitear.
- Recomendación: `--report` y `--out` con default `<kit>/corrections.json` y `<kit>/manual-draft.md`; resolver `--fixes` relativo al directorio de la skill (`$SCRIPT_DIR/../references/...`) o documentar rutas absolutas; agregar ambos al `.gitignore`.
- Cómo verificar el arreglo: correr los 4 comandos del `SKILL.md` desde `/` → los únicos archivos nuevos aparecen dentro del kit.

### [MEDIO] "Reanudable / no pierde nada" está sobrevendido: la etapa cara no reanuda y el OCR aborta entero ante un fallo
- Dónde: `SKILL.md:39-43, 105-106` ("Si se corta, no pierde nada"), `README.md:66-93` (medición "25 s → 1 s" sobre un clip), `scripts/x-video-to-manual.sh:8` (`set -euo pipefail`), `:203,205` (`tesseract … | sed … >>` dentro del for), `:263-265`.
- Evidencia: la caché es por etapa; Whisper es una sola etapa que representa ~90% del tiempo (fable: ASR 21m48s de 24m25s totales según `.stages.json`). Si el proceso muere durante whisper, `transcript.srt` no existe, la etapa no se marca y se rehace desde cero. Con `pipefail`, si tesseract devuelve ≠ 0 en un frame cualquiera el script termina en ese punto sin `mark ocr`, y la próxima corrida repite los 89 frames.
- Impacto: expectativa falsa para el agente (que es quien decide si relanza o no) y pérdida de hasta una hora de CPU en el host compartido.
- Recomendación: ajustar la doc ("reanuda entre etapas; la transcripción se rehace entera"); en el OCR, `|| true` por frame y registrar frames fallidos; opcional: transcribir por chunks de audio (ffmpeg `-f segment`) y cachear por chunk.
- Cómo verificar el arreglo: matar whisper a mitad y relanzar → debe reanudar desde el chunk siguiente; reemplazar un `f_0NN.jpg` por un archivo vacío → el OCR completa el resto y avisa.

### [MEDIO] El borrador es enorme y redundante, no está testeado, y en la práctica no se usa
- Dónde: `scripts/build_manual.py:24, 76-90, 112-123` (embebe `timeline.md` completo —que ya trae el OCR de cada slide— más 400 líneas de OCR más la transcripción), `SKILL.md:94-99` ("Con el borrador + `slides-ocr.txt`, escribir el manual final"). Sin tests para `build_manual.py` (ninguno en `tests/`).
- Evidencia: `manual-draft.md` de heyfredds: 151.800 bytes; `slides-ocr.txt`: 175.918 bytes → ~330 KB (~80–100k tokens) que la doc le pide al LLM que lea. El manual final se escribió a las 13:11 ART y el borrador a las 13:10 (mtimes): un minuto, imposible haberlo procesado; el manual final no cita el borrador ni el timeline.
- Impacto: costo de contexto altísimo o, más probable, el paso se saltea y la redacción sale de la transcripción cruda sin la alineación con slides que es la propuesta de valor.
- Recomendación: que el borrador sea un índice (secciones por slide con 1–2 líneas de OCR y el rango de tiempo, no el texto completo) y que la doc indique leer `timeline.md` por tramos; tope de tamaño con aviso; tests mínimos de `build_manual.py` (usa `clean` si existe, no renormaliza, TODO cuando falta timeline).
- Cómo verificar el arreglo: borrador < 30 KB para un video de 20 min; `pytest tests/test_build_manual.py` verde.

### [MEDIO] Instrucciones de redacción insuficientes; salida final sin convención de ubicación ni nombre
- Dónde: `SKILL.md:94-99` (paso 5 son 4 líneas; el template de `templates/manual-template.md` se menciona como "sugerido"), sin ninguna línea sobre dónde ni cómo nombrar el manual final ni el kit (`--out ./xvm-out` de ejemplo).
- Evidencia: heyfredds `manual-heyfredds-trading-bot-claude.md`: sin apéndice de transcripción (pide a la doc `SKILL.md:98`), sin apéndice de correcciones, un solo `[?]` y en una leyenda, "Orador: (fred)" sin verificación en placa, y una sección editorial ("¿Real o humo?", "Qué sirve para nuestro stack (microcap-screener / Argos)") que no sale del video. Fable `MANUAL-FINAL.md`: cumple el template, 15 `[?]`, verificación de orador razonada. Misma skill, dos resultados de calidad opuesta. Ubicaciones y nombres reales (`inventario-salidas.txt`): `xvm/<autor>-<id>/manual.md` idéntico byte a byte a `manual-<slug>.md` (cmp), `MANUAL-FINAL.md` en `manuals/xvm-20260928-fable/`, fuente en `tmp/xvm2/src.mp4`, un PDF llamado `Manual — Build 10K Websites with Claude Opus 5.5 (Dean W. Perkins).pdf`, y 5 manuales `.md` listados fuera de los kits.
- Impacto: calidad no reproducible y salidas imposibles de encontrar o versionar; riesgo de `.md` sueltos en la raíz del workspace.
- Recomendación: en `SKILL.md`, un checklist obligatorio para el paso 5 (cabecera con fuente/orador verificado/idioma, `[?]` en cuerpo, apéndice de correcciones y transcripción, sin opinión salvo pedido explícito) y una convención única: kit en `xvm/<autor>-<id>/`, final en `manuals/<fecha>-<slug>.md` + `.pdf`, sin duplicados.
- Cómo verificar el arreglo: el próximo manual pasa el checklist y `ls workspace/*.md` no crece.

### [MEDIO] Idioma forzado desde el post, no desde el audio; la doc no lo advierte
- Dónde: `muestras/chain-heyfredds.sh:9` (`--lang es`), `SKILL.md:113` (solo dice que no existe `--language auto`), `SKILL.md:118-119` (advierte sobre el orador, no sobre el idioma).
- Evidencia: el audio es inglés (log completo en inglés; el propio manual, línea 4: "audio en inglés (el post está en español, el video no)"). La transcripción trae errores compatibles con idioma forzado (`Claudia`, `hoddle beta`, `whip swords`, `12-ally`, `the guy that'll leave down below` por "the guide that I'll leave") y la corrida tardó ~50 min para 17,7 min de audio (≈2,8×) frente a 1,72× medidos en fable (21m48s / 12,66 min) con autodetección. No puedo probar la causalidad sin re-correr.
- Impacto: peor transcripción y más CPU por una decisión del agente que la skill no previene.
- Recomendación: gotcha explícito: "no pasar `--lang` según el idioma del post; dejar autodetectar o confirmar con los primeros 30 s". Opcional: el script detecta idioma con `whisper --model tiny` sobre 30 s antes de decidir.
- Cómo verificar el arreglo: re-correr heyfredds sin `--lang` (con `--force` solo del ASR) y comparar las 5 frases citadas.

### [MEDIO] Entrada no confiable sin advertencias: URLs arbitrarias, rutas locales arbitrarias y texto de terceros que va directo al LLM
- Dónde: `scripts/x-video-to-manual.sh:108,117-119` (`[ -f "$SRC" ]` → copia cualquier archivo legible), `:122-123` (yt-dlp sin restricción de dominio ni playlist), `SKILL.md` (ninguna mención a tratar OCR/transcripción como datos no confiables).
- Evidencia: el flujo es "usuario manda link por WhatsApp/Telegram → el agente con shell lo procesa y lee 176 KB de texto de pantalla + transcripción". No hay inyección de shell (las variables van entre comillas y no pasan por `eval`), pero el contenido del video entra al contexto del agente sin marco.
- Impacto: un video con texto en pantalla del tipo "ignore previous instructions…" es un vector de inyección indirecta contra un agente con exec en un host de producción; una URL de playlist/canal dispara descargas múltiples (`for f in "$OUT"/dl.*` toma la primera).
- Recomendación: en `SKILL.md`, indicar que transcript/OCR son datos, nunca instrucciones; `--no-playlist` y allowlist de dominios (`x.com`, `twitter.com`, `youtube.com`) salvo flag explícito; rechazar rutas locales fuera del workspace.
- Cómo verificar el arreglo: `x-video-to-manual.sh /etc/hostname` → error claro; URL de playlist → error o un solo video.

### [MEDIO] Sin limpieza de artefactos pesados
- Dónde: `scripts/x-video-to-manual.sh` (no hay opción de limpieza), `SKILL.md` (no dice qué borrar ni cuándo).
- Evidencia: cada kit conserva `video.mp4` (184.898.260 B en heyfredds, 212.775.395 B en fable según `meta.txt`), `audio.wav` (~34 MB a 16 kHz mono para 17 min) y `frames/`; `inventario-salidas.txt` lista 4 kits con todo eso, más una copia extra del fuente en `tmp/xvm2/src.mp4`.
- Impacto: ~250 MB por video en un VPS chico compartido, sin política; a 2–3 videos por semana se llena el disco en meses.
- Recomendación: `--keep-media` opt-in y por defecto borrar `video.mp4`/`audio.wav` al terminar (dejar frames y textos); o instrucción en `SKILL.md` de borrar tras entregar el manual; un cron de retención.
- Cómo verificar el arreglo: `du -sh workspace/xvm/*` tras una corrida sin `--keep-media` < 20 MB.

### [BAJO] Inconsistencias doc ↔ código y referencias a herramientas ausentes
- Dónde: `scripts/x-video-to-manual.sh:257` y `scripts/stages.py:4-5` ("~0.5x realtime", "20 min tarda ~40") vs `SKILL.md:103-104` / `README.md:68` ("1,8×"); `README.md:219` repite la frase de la línea 213; `SKILL.md:24` y `README.md:35` nombran `pandoc` (no instalado en el VPS) y no dan ningún comando de PDF, así que el agente improvisa (`manual.html` + `.pdf` en cada kit, `inventario-salidas.txt:6-9`); `scripts/x-video-to-manual.sh:127` sugiere `--cookies-from-browser firefox` en un VPS headless.
- Impacto: fricción y decisiones ad hoc del agente.
- Recomendación: unificar la cifra, agregar un `scripts/to_pdf.sh` con `markdown` + `wkhtmltopdf` (lo que sí está instalado) y sacar la sugerencia de cookies o marcarla "solo en desktop".
- Cómo verificar el arreglo: `grep -rn "0.5x" scripts/` vacío; `to_pdf.sh manual.md` produce el PDF.

### [BAJO] Detalles de `stages.py`
- Dónde: `scripts/stages.py:44-49` (firma de directorio por nombre+tamaño, no contenido), `:99-106` (outputs con rutas absolutas), sin lock.
- Evidencia: `.stages.json` de fable guarda `/opt/openclaw-prod/…/manuals/xvm-20260928-fable/…`; mover o renombrar el kit invalida todas las etapas (dirección segura, pero rehace ~25 min). Dos corridas al mismo `--out` escriben el mismo JSON sin coordinación.
- Recomendación: guardar outputs relativos al kit; hashear muestras de los frames; `flock` sobre `.stages.json`.
- Cómo verificar el arreglo: `mv kit kit2 && x-video-to-manual.sh … --out kit2` → todo en caché.

### [BAJO] Reglas del TSV sin límites de palabra
- Dónde: `references/fixes/anthropic-agents.tsv:28-29` (`furnace`→`harness`, `MCT`→`MCP` sin `\b`), `:26` (`entropic` solo en minúscula).
- Impacto: "furnace" legítimo o "MCTS" quedan mal; es opt-in y de dominio, así que bajo.
- Recomendación: `\bfurnace\b`, `\bMCT\b`, `(?i)entropic`; test negativo.
- Cómo verificar el arreglo: `apply_fixes('MCTS furnaces', rules)` no toca "MCTS".

### [BAJO] `meta.txt` filtra rutas internas del VPS al borrador y al manual
- Dónde: `scripts/x-video-to-manual.sh:149` (`source=$SRC`), `scripts/build_manual.py:98-101` (embebe `meta.txt`).
- Evidencia: `muestras/corrida-2026-09-28-fable/meta.txt:7` → `source=/opt/openclaw-prod/agentes/lango/workspace/tmp/xvm2/src.mp4`.
- Recomendación: guardar `basename` para fuentes locales, o no embeber `source` en el borrador.
- Cómo verificar el arreglo: `grep opt/openclaw manual-draft.md` vacío.

### [BAJO] La skill no declara sus binarios requeridos al gateway
- Dónde: `SKILL.md:1-4` (frontmatter solo con `name`/`description`).
- Evidencia: OpenClaw marca la skill `ready` sin comprobar `whisper`, `yt-dlp` ni `tesseract`; el chequeo recién ocurre en `x-video-to-manual.sh:75-77`.
- Recomendación: si la versión de OpenClaw lo soporta, `metadata.openclaw.requires.bins: [yt-dlp, ffmpeg, whisper]` para que la skill no aparezca disponible donde no puede correr (relevante si se porta a la Mac).
- Cómo verificar el arreglo: `openclaw skills list` en un host sin whisper la muestra como no disponible.

### [BAJO] Repo público con la transcripción íntegra de una charla ajena
- Dónde: `examples/claude-managed-agents-manual.md` (23 KB, transcripción completa + nombre del orador) y `.pdf` (111 KB).
- Evidencia: `README.md:248-253` deslinda responsabilidad, pero el repo mismo redistribuye el contenido.
- Recomendación: dejar un ejemplo recortado (2–3 secciones) o pedir permiso al orador.
- Cómo verificar el arreglo: `examples/` sin transcripción completa.

## Deuda no registrada

El proyecto no lleva registro de deuda (no hay HANDOFF/PROGRESO/SPEC ni issues en el repo). Lo que debería quedar registrado, además de los hallazgos de arriba:

- Deploy de la skill al workspace de Lango: hoy es copia manual sin procedimiento (origen del desfase).
- Sin tests para `build_manual.py` ni para el cableado de caché en el `.sh` (`cached`/`mark`); los tests visuales de `align_slides` se saltean en silencio si el runner no tiene ffmpeg (`tests/test_align_slides.py:155-157, 173-175`).
- CI prueba solo `python-version: '3.x'` (la última); la versión de Python del VPS no está fijada ni testeada.
- Tres propuestas del skill-workshop de OpenClaw sin decisión (`/root/.openclaw-prod/skill-workshop/proposals/x-video-to-manual-2026092{6,7}-*`).
- Retención/limpieza de kits y política de nombres de salida.
- `retrans.done`/`retrans.log` en el kit `EngMoElgaraihy-…`: hubo una re-transcripción manual fuera del script cuyo motivo no está documentado.

## Sospechas sin confirmar

- **Token count del vocabulario > 223.** Sostiene el hallazgo ALTO del orden invertido; no pude ejecutar tiktoken (bloqueado por el guardia). Confirmar con el comando de "Verificaciones pendientes".
- **`--lang es` como causa de la peor transcripción y de los ~50 min.** Correlación clara, causalidad no probada; alternativas: carga concurrente en el host (el chain esperaba a otro whisper, pero el gateway y 5 agentes seguían activos).
- **Manuales `.md` en la raíz del workspace de Lango.** `inventario-salidas.txt:1-5` lista 5 manuales sin ruta; si están en la raíz, chocan con la regla ya aprendida en este stack de que muchos `.md` en la raíz revientan el system prompt.
- **Permisos de la copia instalada.** En el mirror local los scripts son `711` y `anthropic-agents.tsv` es `600`; si el gateway corre con un usuario distinto al dueño, el TSV es ilegible (0 correcciones también por eso). Los permisos pueden no haberse preservado en la copia; hay que mirar el VPS.
- **El agente no lee el borrador.** Un minuto entre `manual-draft.md` (13:10) y el manual final (13:11) y ninguna referencia al timeline en el manual heyfredds. Confirmar con la sesión/transcript del agente.
- **`dl.*` residuales.** Si una descarga anterior dejó `dl.mp4.part` o `dl.f137.mp4`, el glob de `x-video-to-manual.sh:133` puede tomar un archivo parcial y cachearlo como `video`. No vi un caso; requiere probar.

## Verificaciones pendientes

No autorizadas o bloqueadas por el guardia; ninguna se corrió:

- `cd repo-github && pytest -q` (no hay pytest en esta máquina; el CI lo corre en GitHub, no vi el estado del último run).
- `shellcheck scripts/*.sh` y `bash -n scripts/x-video-to-manual.sh` (linters no autorizados).
- Conteo de tokens del vocabulario: `python3 -c "import tiktoken;e=tiktoken.get_encoding('gpt2');print(len(e.encode(' '+open('muestras/corrida-2026-09-29-heyfredds/vocab.txt').read().strip())))"` (bloqueado: código inline en intérprete). Esperado hoy: > 223.
- En el VPS: `diff -rq workspace/skills/x-video-to-manual workspace/repos/x-video-to-manual -x .git`; `openclaw --profile prod skills list`; `ls -la workspace/skills/x-video-to-manual/scripts workspace/skills/x-video-to-manual/references/fixes` y `systemctl show -p User <unidad del gateway>`; `du -sh workspace/xvm/* workspace/manuals/*`; `ls workspace/*.md`; `python3 --version`; `free -m` y `top -o %CPU` durante una corrida de whisper; contenido de las 3 propuestas del skill-workshop; `cat workspace/xvm/EngMoElgaraihy-*/retrans.log`.
- Un `find … -exec ls -la` inicial fue bloqueado; lo reemplacé por `find` + `ls -laR`, sin pérdida.
- Ejecutar el pipeline (descarga, ffmpeg, whisper) quedó fuera por diseño del brief.

## Qué está bien

- Motor de correcciones opt-in, sin reglas hardcodeadas, con prioridad y longitud, y con reporte JSON de cada cambio (`normalize_transcript.py`); el caso "Google Cloud ≠ Google Claude" está pensado y testeado.
- `srt.py` como parser único, tolerante a CRLF/BOM/coma-punto/sin índice, con tests; `align_slides.py` con fallback a texto y protecciones contra numeración con huecos.
- `stages.py`: firmas por parámetros + muestreo de archivos, invalidación ante salida borrada o estado corrupto, 15 tests que cubren justo lo que importa (que un cambio invalide).
- CI en dos sistemas operativos con pytest, shellcheck y un test de que `--help` no filtre código; licencia y atribución claras.
- El manual de la corrida fable es un buen ejemplo de lo que la skill promete: orador verificado con razonamiento, 15 `[?]`, apéndice de correcciones manuales y transcripción corregida.
