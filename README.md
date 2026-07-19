# ⚔️ KnightForge Sahayak

### AI-Assisted KYC Paperwork Copilot

**KnightForge Sahayak** transforms repetitive and complex KYC paperwork into one intelligent, guided workflow.

Users can upload a supported KYC form along with supporting documents such as PAN, Aadhaar, Driving Licence, and bank/account documents. Sahayak classifies documents, extracts and validates information, builds a unified **Canonical KYC Profile**, identifies genuinely missing information, guides the user through completion, and generates a completed version of the original KYC form.

Built for **OpenAI Build Week 2026** with **OpenAI Codex** as an engineering collaborator for implementation, debugging, testing, architecture iteration, and production hardening.

---

## 🎬 Live Demo

🌐 **Application:**  
https://knight-forge-sahayak.vercel.app/

> **Note:** The deployed backend uses a free-tier service and may require a short wake-up period after inactivity.

---

## 💡 The Problem

KYC onboarding is repetitive and fragmented.

The same identity and personal information often needs to be entered across multiple financial forms, each with different:

- layouts and terminology
- required fields
- checkboxes and choice fields
- document requirements
- photograph and signature regions

Manually copying information between identity documents and KYC forms is time-consuming and error-prone.

**KnightForge Sahayak turns this fragmented process into one reusable KYC workflow.**

---

## ✨ Core Features

- 📄 **Multi-Form KYC Support** — Supports CVL/CDSL, SBI, HDFC, ICICI, and Axis Bank KYC workflows
- 🔍 **Automatic Document Classification** — Identifies primary KYC forms and supported evidence documents
- 🧠 **OCR & Structured Extraction** — Extracts useful information from uploaded documents
- 👤 **Canonical KYC Profile** — Merges information from multiple sources into one unified profile
- ⚖️ **Conflict Resolution** — Detects conflicting evidence instead of silently overwriting values
- 📝 **Partial-Form Preservation** — Preserves valid information already present in uploaded forms
- 💬 **AI-Guided Completion** — Asks only for genuinely missing or applicable information
- 📊 **Dynamic Progress Tracking** — Tracks completion against the requirements of the selected KYC form
- ✅ **Deterministic Validation** — Validates structured fields instead of relying entirely on AI
- 🖼️ **Photo & Signature Handling** — Supports applicant image assets separately from text data
- 📐 **Geometry-Aware PDF Placement** — Uses form-specific manifests and measured PDF regions
- ☑️ **Checkbox & Choice Placement** — Handles option fields using verified form geometry
- 📑 **PDF Generation** — Generates a completed copy while preserving the original uploaded document
- 🕘 **PDF Version History** — Retains generated versions for preview and download
- 📚 **Knowledge Chat** — Provides grounded KYC assistance with retrieval and supporting citations
- 🔐 **Resource Ownership Isolation** — Protects user sessions, documents, profiles, assets, and generated PDFs

---

## 🔄 How Sahayak Works

```text
KYC Form + Supporting Documents
              │
              ▼
     Document Classification
              │
              ▼
         OCR & Extraction
              │
              ▼
   Validation & Evidence Merge
              │
              ▼
     Canonical KYC Profile
              │
              ▼
 Identify Missing / Conflicting Fields
              │
              ▼
      AI-Guided Completion
              │
              ▼
      Photo + Signature Assets
              │
              ▼
   Form-Specific Placement Engine
              │
              ▼
       Generated KYC PDF
              │
              ▼
   Preview / Download / Versioning
```

The core design principle is:

> **Use AI where interpretation is valuable, and deterministic logic where correctness, validation, placement, and authorization matter.**

Sahayak is therefore not simply an **"upload a PDF → ask an LLM to fill it"** application.

---

## 🧩 Canonical KYC Profile

Different documents may contain overlapping information.

For example:

```text
PAN ───────────────┐
Aadhaar ───────────┤
Driving Licence ───┤
Bank Documents ────┼──► Canonical KYC Profile
Existing KYC Form ─┤
User Answers ──────┘
```

The Canonical KYC Profile acts as the unified representation of the user's KYC information.

The system can:

- combine evidence from multiple documents
- validate extracted values
- track provenance and confidence
- detect conflicting information
- preserve existing valid values
- determine which fields are still missing

This allows the same verified information to be reused across heterogeneous KYC forms.

---

## 📄 Supported Primary KYC Forms

| KYC Form | Status |
|---|---|
| CVL / CDSL Individual KYC | ✅ Supported |
| SBI KYC Updation — Annexure A | ✅ Supported |
| HDFC KYC | ✅ Supported |
| ICICI / Central KYC Registry | ✅ Supported |
| Axis Bank / Central KYC Registry | ✅ Supported |

Users can work with supported blank templates or upload compatible copies of their own forms.

---

## 📎 Supporting Documents

The document intelligence pipeline can process supported identity and account evidence such as:

- PAN
- Aadhaar
- Driving Licence
- supported bank/account documents
- existing or partially completed KYC forms

Document **classification** and **field extraction** are intentionally separated so that the system can reason about the type of evidence before merging extracted information.

---

## 📐 Smart PDF Generation

Each KYC form has a different physical layout.

Sahayak uses **form-specific placement manifests** to map canonical profile fields into measured regions of the target PDF.

The PDF pipeline handles:

- text placement
- checkbox and choice fields
- photograph placement
- signature placement
- form-specific requirements
- partial-form preservation
- exclusion of office-use/institution-only regions
- preservation of the original uploaded PDF
- generated PDF version history

This geometry-aware approach allows multiple heterogeneous KYC forms to share one canonical data model while retaining their individual layouts.

---

## 📚 Knowledge Chat

Sahayak includes a KYC-focused Knowledge Chat for users who need help understanding forms or requirements.

The retrieval pipeline uses:

- ChromaDB vector storage
- MiniLM embeddings
- ONNX-based inference
- retrieval-augmented generation (RAG)
- grounded responses with citations
- workflow-aware assistance

The knowledge system is designed to retrieve relevant KYC information before generating an answer rather than operating as a generic standalone chatbot.

---

## 🏗️ Architecture

```text
                    ┌─────────────────────────┐
                    │          User           │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Next.js / React UI    │
                    │ TypeScript + Tailwind   │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │      FastAPI API        │
                    │        Python           │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
     ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
     │   Document     │ │   Knowledge    │ │ Authentication │
     │ Intelligence   │ │      RAG       │ │  & Ownership   │
     └───────┬────────┘ └───────┬────────┘ └────────────────┘
             │                  │
             ▼                  ▼
     OCR / Classification   ChromaDB / ONNX
     Extraction / Merge     MiniLM / AI
     Validation
             │
             ▼
     ┌───────────────────┐
     │ Canonical Profile │
     │ Conflict Resolution│
     └─────────┬─────────┘
               │
               ▼
     ┌───────────────────┐
     │ AI-Guided         │
     │ Completion        │
     └─────────┬─────────┘
               │
               ▼
     ┌───────────────────┐
     │ PDF Placement     │
     │ Engine            │
     └─────────┬─────────┘
               │
               ▼
       Generated KYC PDF
```

### Production Infrastructure

```text
Frontend
   │
   └──► Vercel
          │
          ▼
Dockerized FastAPI Backend
          │
          └──► Render
                 │
          ┌──────┴───────┐
          ▼              ▼
   Neon PostgreSQL   Supabase Storage
   Workflow Data     Private Documents
```

---

## 🛠️ Tech Stack

### Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- Uvicorn
- Docker

### Document Intelligence

- Tesseract OCR
- PyMuPDF
- Pillow
- deterministic field extraction
- document classification
- validation and conflict-resolution rules
- schema-driven form requirements

### AI & Retrieval

- AI-assisted semantic processing
- Retrieval-Augmented Generation (RAG)
- ChromaDB
- ONNX Runtime
- MiniLM embeddings
- Gemini integration

### Data & Storage

- Neon PostgreSQL — production workflow and metadata persistence
- Supabase private object storage — uploaded documents, assets, and generated PDFs
- SQLite — local development where configured

### Authentication & Security

- JWT-based authentication
- refresh-token authentication
- Google OAuth
- server-side resource ownership enforcement
- cross-user isolation
- upload validation
- CORS restrictions
- production configuration safeguards
- rate limiting on sensitive/expensive endpoints

### Deployment

- Vercel — Next.js frontend
- Render — Dockerized FastAPI backend
- Neon — PostgreSQL
- Supabase — private object storage

### Development

- Git
- GitHub
- OpenAI Codex

Codex was used as an engineering collaborator throughout development to accelerate implementation, debug document-processing and deployment issues, reason about PDF geometry, strengthen regression testing, investigate extraction failures, and harden the production system.

---

## 🚀 Running Locally

### Prerequisites

Make sure the following are installed:

- Python 3.12+
- Node.js 20+
- npm
- Git
- Tesseract OCR

Clone the repository:

```bash
git clone <YOUR_REPOSITORY_URL>
cd knightforge-sahayak
```

---

## 1️⃣ Backend Setup

Navigate to the backend:

```bash
cd backend
```

Create a Python virtual environment:

```bash
python -m venv .venv
```

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
```

### macOS / Linux

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy/configure the required environment variables using:

```text
.env.example
```

Do not commit secrets or production credentials.

Run database migrations if required by your configuration:

```bash
alembic upgrade head
```

Start the FastAPI backend:

```bash
uvicorn app.main:app --reload --port 8000
```

The API should be available at:

```text
http://127.0.0.1:8000
```

Verify backend health:

```text
http://127.0.0.1:8000/health
```

FastAPI API documentation:

```text
http://127.0.0.1:8000/docs
```

---

## 2️⃣ Frontend Setup

Open another terminal from the repository root:

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Configure:

```text
.env.local
```

For a local backend, the frontend API base URL should point to:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Start the development server:

```bash
npm run dev
```

Open:

```text
http://localhost:3000
```

Keep both the frontend and backend running.

---

## 🧪 Testing

### Backend Regression Tests

From the `backend` directory, run the available end-to-end/regression suites:

```bash
python e2e_phase15.py
python e2e_phase16.py
python e2e_phase17.py
python e2e_phase18.py
```

Additional project-specific smoke or regression suites can be run according to the scripts available in the repository.

### Frontend Type Check

```bash
cd frontend
npx tsc --noEmit
```

### Frontend Lint

```bash
npm run lint
```

### Production Build Verification

```bash
npm run build
```

A successful production build confirms that the Next.js application compiles correctly for deployment.

---

## 🔐 Security Design

KYC workflows involve sensitive personal information, so Sahayak treats authorization as a backend responsibility.

Key principles include:

- authenticated access to protected resources
- server-side ownership enforcement
- cross-user resource isolation
- private document storage
- protected generated PDFs
- secure production configuration
- restricted CORS origins
- validation of uploaded content
- separation of AI reasoning from authorization decisions

AI is used to assist interpretation and completion.

**AI is not the security boundary.**

---

## ⚙️ Engineering Challenges

Several challenges required more than simply connecting an LLM to a PDF.

### Different Form Layouts

Every KYC form has different geometry.

**Solution:** Form-specific placement manifests and schema-driven requirements.

### False Extraction from Blank Forms

Printed labels can be mistaken for applicant data.

**Solution:** Region-aware extraction and validation rather than blindly accepting nearby text.

### Partially Completed Forms

Existing user information should not be overwritten unnecessarily.

**Solution:** Non-destructive merge and placement rules.

### Conflicting Documents

Multiple documents may provide different values.

**Solution:** Canonical profile with provenance, validation, confidence, and conflict resolution.

### Checkbox and Choice Fields

These cannot be handled like ordinary text fields.

**Solution:** Verified option rectangles and form-specific placement strategies.

### Photos and Signatures

These are image assets rather than text fields.

**Solution:** Dedicated asset workflow with measured placement regions.

### Cloud Persistence

Application state and uploaded documents must survive backend container replacement.

**Solution:** Persistent workflow data in PostgreSQL and private object storage for documents and generated assets.

### Production Hardening

Several issues only appeared under real deployment conditions.

**Solution:** Production smoke testing, persistence verification, ownership-isolation testing, and regression-driven fixes.

---

## ⚠️ Deployment Notes

The public demo uses free-tier infrastructure.

The backend may require a short wake-up period after inactivity. OCR is also computationally intensive and processing time depends on document size, scan quality, and available compute.

These infrastructure constraints do not affect the core architecture and can be addressed in a production deployment using always-on compute, background processing, and scalable workers.

---

## 🔮 Future Improvements

Potential next steps include:

- support for additional banks and government forms
- background OCR/document-processing workers
- persistent document-understanding cache
- asynchronous processing with real-time progress updates
- improved OCR adapters for production-scale workloads
- scalable caching and job queues where appropriate
- human-in-the-loop verification
- reusable consent-driven identity profiles
- expanded multilingual document understanding
- stronger observability and production monitoring

---

## 🏆 Built For

**OpenAI Build Week 2026**

KnightForge Sahayak explores how AI and deterministic document intelligence can work together to transform repetitive paperwork into a guided, understandable, and reusable workflow.

The project was built iteratively with **OpenAI Codex** supporting implementation, debugging, testing, architecture iteration, and engineering hardening.

---

## ⚠️ Disclaimer

KnightForge Sahayak is an AI-assisted paperwork tool built for demonstration and hackathon purposes.

It is not a substitute for official financial, legal, regulatory, or compliance advice.

Users should always review extracted information and generated documents before submitting them to any institution.

---

## 👨‍💻 Author

**Prasad Nathe**

---

## 📜 License

This project is intended for demonstration, educational, and hackathon purposes.
