# Manual: De modelo a agente en producción
## Messages API → Claude Agent SDK → Claude Managed Agents

**Fuente:** video de X (11 min 52 s) — post de **Mo Elgaraihy** (@EngMoElgaraihy), 26 SEP 2026
**Link:** https://x.com/engmoelgaraihy/status/2103658343512297936
**Charla:** "Agentic Engineering Summit" (AWS Builder Loft, con branding AWS) — lightning talk
**Orador:** **Gagan Bhat**, Member of Technical Staff en **Anthropic** *(según la placa de título del video: "Gagan Bhat — Member of Technical Staff | ANTHROPIC"; en el audio se presenta como "product engineer at Anthropic")*. El post de X es de Mo Elgaraihy, que difundió la charla.
**Procesado por:** Lango (yt-dlp → ffmpeg → Whisper small → OCR de slides con tesseract)

> Nota de fidelidad: la transcripción automática confundía sistemáticamente *"agent/agentic"* con *"Asian"* y *"Claude"* con *"Cloud"*. Este manual está **corregido**, con las correcciones dudosas marcadas como `[?]`. Al final hay un apéndice con la transcripción cruda y el detalle de correcciones.

---

## 1. Resumen ejecutivo (TL;DR)

La charla explica **cómo evolucionó la "superficie" que usa un dev para construir agentes** en Anthropic, en tres niveles acumulativos. Cada nivel te quita una capa de infraestructura de encima:

| Nivel | Producto | Qué te da Anthropic | Qué seguís construyendo vos |
|---|---|---|---|
| 1 | **Messages API** | El **modelo** (tokens in / tokens out) | *Todo*: loop agéntico, contexto, tools, sesiones, auth, observabilidad |
| 2 | **Claude Agent SDK** | El **harness agéntico** (loop, tools built-in, sandbox, filesystem) | Hosting, escalado, estado de sesión, observabilidad, tools custom |
| 3 | **Claude Managed Agents** | El **harness + runtime + sandbox + sesiones + auth + vault + hosting + observabilidad** | El **producto** y la lógica de negocio |

**Tesis central:** con Managed Agents pasás de *"horas para el prototipo y semanas para producción"* a **shipear rápido sin reescribir nada** — el mismo código de prototipo es *production-grade*.

**Cambio arquitectónico clave:** el **loop agéntico se separa del sandbox**. El "cerebro" (modelo + orquestación) vive en el cloud; las "manos" (tools, sandbox) se levantan **solo cuando se necesitan**. Antes, loop y ejecución de tools compartían contenedor → latencia alta en cada arranque y *single point of failure*.

---

## 2. La evolución de las superficies agénticas (3 slides)

### Nivel 1 — `01 Messages API`
> **Slide:** *"The model is provided. Everything around it is yours to build."*

- Antes, Anthropic te daba **tokens in / tokens out**. Nada más.
- Diagrama del slide:
  - **Your product** → **Agentic loop** *(calls Claude, runs tools, manages context)* → **Claude Messages API**
  - **Production infrastructure** (todo *run by you*): session management · hosting · observability · credentials · infrastructure
- Vos manejabas: loop agéntico, manejo de contexto, ejecución de tools, estado de sesión y recovery, auth, observabilidad, lógica de tool custom.

### Nivel 2 — `02 Claude Agent SDK`
> **Slide:** *"The agentic harness is provided."*

- Aparece **Claude Code** (la implementación de Anthropic de un *agentic harness*) y se empaqueta como **Claude Agent SDK**.
- Ahora el SDK te provee: **el loop agéntico + el harness**, manejo de contexto, ejecución de tools built-in, **sandbox** y **filesystem**.
- Por debajo sigue usando Messages API (tokens in / out).
- **Vos seguís manejando:** hosting y escalado, estado de sesión, observabilidad, lógica de tools custom. → *Todavía hay mucho trabajo para llevar el agente a producción.*

### Nivel 3 — `03 Claude Managed Agents`
> **Slide:** *"You own the product. Agents are production ready."*

- Vos traés **solo**: tu *task* + la **config del agente** + tu **lógica de tools custom** (si hace falta).
- Anthropic maneja: harness purpose-built · runtime de tools + **sandbox** · estado de sesión, persistencia y **checkpointing** · auth y **credential vaults** (guardado seguro de API keys de tus otros servicios) · hosting, escalado y observabilidad.
- Por debajo, sigue siendo tokens in / tokens out.
- **Slide 03 — arquitectura final:**
  - **Your product** → **Agentic loop** *(caching, compaction, and tools built in)* → **Claude Messages API**
  - **Sandbox:** contenedor seguro con **filesystem persistente**
  - **Credentials:** auth y secrets gestionados
  - **Production infrastructure:** session management · hosting · observability
- **Recomendación explícita del orador:** si querés ir de *idea* a un agente feature-rich en tu producto, **empezá por Managed Agents**.

---


---

> **Extracto.** Este ejemplo muestra solo el encabezado, el resumen y la primera sección
> del manual que generó la skill. El manual completo incluía la transcripción íntegra de
> la charla, que pertenece a su autor: no se redistribuye en este repo (ver
> *Contenido y derechos* en el README).
