# Diagrams for the Lena README

Both diagrams below are written in Mermaid, which GitHub renders automatically.
Copy either ```mermaid block straight into README.md — a good placement is a
new "## How It Works" section right after "## Key Features".

---

## Diagram 1 — Call lifecycle

```mermaid
flowchart TD
    A["POST /start-call"] --> B{"Opt-out list check<br/>(enforced in code)"}
    B -- "number opted out" --> B1["Call refused"]
    B -- "clear" --> C["Twilio dials the caller"]
    C --> D["Lena greets +<br/>AI disclosure (mandatory)"]

    subgraph LOOP ["Conversation loop — every turn"]
        E["Caller speaks<br/>(Twilio speech-to-text)"] --> F["Trigger scan<br/>steering bait · distress · legal ·<br/>opt-out · prompt injection"]
        F --> G["Claude reasons +<br/>calls tools"]
        G --> H["Tools<br/>availability · book viewing ·<br/>approved concessions only"]
        H --> G
        G --> I{"Output guardrail<br/>(deterministic filter)"}
        I -- "violation" --> J["Blocked — safe fallback<br/>spoken instead, event logged"]
        I -- "clean" --> K["Reply spoken<br/>(text-to-speech)"]
        J --> E
        K --> E
    end

    D --> LOOP
    LOOP --> L["Call ends"]
    L --> M["QA supervisor grades<br/>100% of the transcript"]
    L --> N["Handoff summary generated<br/>outcome · priority · follow-ups"]
    L --> O["SMS confirmation composed<br/>(log / twilio mode)"]
    M --> P[("Hash-chained<br/>audit log — SQLite")]
    N --> P
    O --> P
    P --> Q["Leasing dashboard<br/>/dashboard"]
```

---

## Diagram 2 — System architecture

```mermaid
flowchart LR
    subgraph CALLER ["Caller"]
        PH["Phone"]
    end

    subgraph TEL ["telephony/ — thin, swappable adapter"]
        TW["Twilio adapter<br/>(FastAPI webhooks)"]
        DB2["Leasing dashboard<br/>+ /api/calls"]
    end

    subgraph CORE ["agent/ — conversation engine (text-first)"]
        TRG["compliance/triggers.py<br/>input trigger detection"]
        LLM["Claude<br/>+ tool-use loop"]
        GRD["compliance/guardrail.py<br/>deterministic output filter"]
    end

    subgraph RULES ["config/ — the vertical, as data"]
        LST["property_listings.json"]
        CON["concessions.json<br/>(approved offer menu)"]
        FHR["compliance_rules.json<br/>(fair-housing rules)"]
    end

    subgraph POST ["Post-call"]
        QA["supervisor/qa.py<br/>QA on every transcript"]
        SUM["supervisor/summary.py<br/>leasing handoff summary"]
        SMS["notifications/sms.py<br/>booking confirmation"]
    end

    subgraph STORE ["db/"]
        AUD[("SQLite +<br/>SHA-256 hash chain")]
    end

    subgraph EVALS ["evals/ — validation"]
        PER["20 red-team personas"]
        SIM["LLM-simulated callers"]
        AB["A/B prompt harness"]
    end

    PH <--> TW
    TW --> TRG --> LLM --> GRD --> TW
    LLM <--> CON
    LLM <--> LST
    TRG -.-> FHR
    GRD -.-> FHR
    GRD -.-> CON
    TW --> QA & SUM & SMS
    QA & SUM & SMS --> AUD
    AUD --> DB2
    PER --> SIM --> CORE
    SIM --> QA
```

---

## Suggested README section

Paste this whole block into README.md after "## Key Features":

```markdown
## How It Works

### Call lifecycle

<paste Diagram 1 mermaid block here>

Every reply passes through two independent compliance layers before it is
spoken: trigger detection on the caller's words, and the deterministic
guardrail on the agent's words. On call completion, the QA supervisor,
handoff summary, and SMS composition all write into the hash-chained audit
log, which the dashboard renders read-only.

### System architecture

<paste Diagram 2 mermaid block here>

The engine is text-first: the same core powers the terminal demo, the
evaluation suite, and the phone adapter. The vertical (listings, offers,
fair-housing rules) lives entirely in `config/` as data, which is what makes
the architecture domain-agnostic.
```
