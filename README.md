⚔️ KnightForge Sahayak
AI Paperwork Copilot | OCR • RAG • Knowledge Graph • Automated KYC
KnightForge Sahayak is an individual AI-powered KYC paperwork copilot that turns repetitive document onboarding into one guided, evidence-backed workflow.

Users can upload a supported KYC form with supporting documents such as PAN, Aadhaar, Driving Licence, and bank/account records. Sahayak classifies documents, extracts 15 KYC fields using Python OCR, validates schema-constrained JSON, resolves conflicting values using confidence and source evidence, and builds a unified Canonical KYC Profile. It then guides users through missing fields and generates a completed version of the original KYC form.

The project also integrates Gemini, Pinecone/ChromaDB-based RAG, MiniLM retrieval, and a NetworkX knowledge graph for grounded assistance and field-level provenance. An evaluation harness measures extraction quality and response faithfulness against a curated KYC test set.

Built for OpenAI Build Week 2026 with OpenAI Codex as an engineering collaborator for implementation, debugging, testing, architecture iteration, and production hardening.
🎬 Live Demo
🌐 Application:
https://knight-forge-sahayak.vercel.app/
Note: The deployed backend uses a free-tier service and may require a short wake-up period after inactivity.

📊 Project Highlights
Capability	Result / Implementation
Structured KYC extraction	15 fields with Python OCR and schema-validated JSON
Evaluation dataset	100 golden KYC samples
Extraction precision / recall / F1	92% / 88% / 90%
RAG response faithfulness	0.89 Ragas score
Measured latency optimization	1.8 s → 650 ms
Evidence provenance	NetworkX graph connecting documents, entities, and sources
Grounded retrieval	Gemini + Pinecone/ChromaDB RAG + MiniLM


These are project-reported evaluation results from the stated test setup, not guarantees for every document, workload, or deployment.
💡 The Problem
KYC onboarding is repetitive and fragmented.

The same identity and personal information often needs to be entered across multiple financial forms, each with different:
- layouts and terminology
- required fields
- checkboxes and choice fields
- document requirements
- photograph and signature regions
Manually copying information between identity documents and KYC forms is time-consuming and error-prone.

KnightForge Sahayak turns this fragmented process into one reusable KYC workflow.
✨ Core Features
- 📄 Multi-Form KYC Support — Supports CVL/CDSL, SBI, HDFC, ICICI, and Axis Bank KYC workflows
- 🔍 Automatic Document Classification — Identifies primary KYC forms and supported evidence documents
- 🧠 15-Field OCR Extraction — Extracts structured KYC information with Python OCR into schema-constrained JSON
- 🧾 JSON Schema Validation — Validates extracted fields and rejects or flags invalid structured values
- 👤 Canonical KYC Profile — Merges information from multiple sources into one unified profile
- ⚖️ Confidence-Aware Conflict Resolution — Compares candidate values using confidence, validation, and source evidence instead of silently overwriting data
- 🕸️ Knowledge-Graph Provenance — Uses NetworkX to connect documents, extracted entities, and supporting evidence for traceable field origins
- 📝 Partial-Form Preservation — Preserves valid information already present in uploaded forms
- 💬 AI-Guided Completion — Asks only for genuinely missing or applicable information
- 📊 Dynamic Progress Tracking — Tracks completion against the requirements of the selected KYC form
- ✅ Deterministic Validation — Validates structured fields instead of relying entirely on AI
- 🖼️ Photo & Signature Handling — Supports applicant image assets separately from text data
- 📐 Geometry-Aware PDF Placement — Uses form-specific manifests and measured PDF regions
- ☑️ Checkbox & Choice Placement — Handles option fields using verified form geometry
- 📑 PDF Generation — Generates a completed copy while preserving the original uploaded document
- 🕘 PDF Version History — Retains generated versions for preview and download
- 📚 Gemini + RAG Knowledge Chat — Uses MiniLM embeddings and Pinecone/ChromaDB retrieval to generate grounded answers with supporting citations
- 🧪 Evaluation & Quality Checks — Tests 100 golden KYC samples, tracks precision/recall/F1 and Ragas faithfulness, and applies rubric-based LLM-as-judge groundedness checks
- 🔐 Resource Ownership Isolation — Protects user sessions, documents, profiles, assets, and generated PDFs
🔄 How Sahayak Works
KYC Form + Supporting Documents
              │
              ▼
     Document Classification
              │
              ▼
     Python OCR: 15 KYC Fields
              │
              ▼
   Schema-Validated JSON Output
              │
              ▼
   Confidence + Evidence Merge
              │
              ▼
    NetworkX Provenance Graph
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
The core design principle is:
Use AI where interpretation is valuable, and deterministic logic where correctness, validation, placement, and authorization matter.

Sahayak is therefore not simply an "upload a PDF → ask an LLM to fill it" application.
🧩 Canonical KYC Profile
Different documents may contain overlapping information.

For example:
PAN ───────────────┐
Aadhaar ───────────┤
Driving Licence ───┤
Bank Documents ────┼──► Canonical KYC Profile
Existing KYC Form ─┤
User Answers ──────┘
The Canonical KYC Profile acts as the unified representation of the user's KYC information.

The system can:
- combine evidence from multiple documents
- extract 15 targeted KYC fields and validate structured JSON against schemas
- retain source documents, extracted entities, confidence, and field-level provenance
- use a NetworkX knowledge graph to trace why a field value was selected
- detect conflicting information and flag values that need user confirmation
- preserve existing valid values
- determine which fields are still missing
This allows the same verified information to be reused across heterogeneous KYC forms.
🕸️ NetworkX Knowledge Graph & Field Provenance
To make extracted values explainable, Sahayak models relationships between source documents, extracted entities/fields, and supporting evidence in a NetworkX knowledge graph.
PAN Document ─────────────┐
                         ├──► Name / DOB / PAN ───► Canonical Profile
Aadhaar Document ────────┤            │
                         │            ▼
Bank Document ────────────┘     Evidence + Confidence
                                      │
                                      ▼
                            Provenance Graph Traversal
                                      │
                                      ▼
                         Explain / Verify Selected Value
Graph traversal helps trace a canonical field back to the document and extracted evidence supporting it. When two documents disagree, confidence and deterministic validation contribute to the merge decision; ambiguous values can be surfaced for review instead of silently accepted.
📄 Supported Primary KYC Forms
KYC Form	Status
CVL / CDSL Individual KYC	✅ Supported
SBI KYC Updation — Annexure A	✅ Supported
HDFC KYC	✅ Supported
ICICI / Central KYC Registry	✅ Supported
Axis Bank / Central KYC Registry	✅ Supported


Users can work with supported blank templates or upload compatible copies of their own forms.
📎 Supporting Documents
The document intelligence pipeline can process supported identity and account evidence such as:
- PAN
- Aadhaar
- Driving Licence
- supported bank/account documents
- existing or partially completed KYC forms
Document classification and field extraction are intentionally separated so that the system can reason about the type of evidence before merging extracted information.
📐 Smart PDF Generation
Each KYC form has a different physical layout.

Sahayak uses form-specific placement manifests to map canonical profile fields into measured regions of the target PDF.

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
📚 Knowledge Chat
Sahayak includes a KYC-focused Knowledge Chat for users who need help understanding forms or requirements.

The retrieval pipeline uses:
- MiniLM text embeddings for semantic retrieval
- Pinecone and ChromaDB vector retrieval components
- ONNX Runtime for supported local embedding inference
- Gemini for AI-assisted responses
- Retrieval-Augmented Generation (RAG) to supply relevant KYC context
- Source-grounded answers with supporting citations
- Rubric-based LLM-as-judge assessment of groundedness
- Ragas faithfulness measurements for evaluation
- Workflow-aware assistance during form completion
Rather than treating the LLM as a standalone source of truth, the retrieval layer supplies relevant context before generation. The graph-based provenance layer complements document citations by making extracted KYC fields traceable to their supporting evidence. The project includes both Pinecone and ChromaDB retrieval components; the configured environment determines which is used in a given flow.
⚡ Retrieval & Response Optimization
In the measured project setup, optimization of the AI/retrieval path reduced latency from 1.8 seconds to 650 milliseconds (about 64% lower latency). This is a benchmark observation and should not be interpreted as a fixed end-to-end response time for every document or free-tier deployment.
🏗️ Architecture
                     ┌──────────────────────────┐
                     │           User           │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │ Next.js / React Frontend │
                     │ TypeScript + Tailwind    │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │   Python FastAPI API     │
                     └────────────┬─────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
 ┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
 │ Document        │    │ Knowledge Chat   │    │ Authentication   │
 │ Intelligence    │    │ Gemini + RAG     │    │ & Authorization  │
 └────────┬────────┘    └─────────┬────────┘    └──────────────────┘
          │                       │
          ▼                       ▼
 ┌─────────────────┐    ┌──────────────────────────────┐
 │ OCR: 15 Fields  │    │ MiniLM + Pinecone/ChromaDB   │
 │ Schema-JSON     │    │ Grounded Answer + Citations  │
 └────────┬────────┘    └──────────────────────────────┘
          │
          ▼
 ┌──────────────────────────────┐
 │ Validation + Confidence      │
 │ Conflict Resolution          │
 └────────┬─────────────────────┘
          │
          ▼
 ┌──────────────────────────────┐
 │ NetworkX Knowledge Graph     │
 │ Entities + Source Provenance │
 └────────┬─────────────────────┘
          │
          ▼
 ┌──────────────────────────────┐
 │ Canonical KYC Profile        │
 │ Missing-Field Guided Flow    │
 └────────┬─────────────────────┘
          │
          ▼
 ┌──────────────────────────────┐
 │ Form-Specific PDF Placement  │
 │ Preview / Download / History │
 └──────────────────────────────┘

 Evaluation (separate test workflow):
 100 Golden Samples → Python Evaluation Harness
   → Precision / Recall / F1 + Ragas Faithfulness
   → Rubric-Based LLM-as-Judge Groundedness
Production Infrastructure
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
🛠️ Tech Stack
Frontend
- Next.js
- React
- TypeScript
- Tailwind CSS
Backend
- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- Uvicorn
- Docker
Document Intelligence
- Tesseract OCR
- PyMuPDF
- Pillow
- deterministic field extraction
- document classification
- schema-constrained JSON extraction for 15 KYC fields
- confidence-aware validation and conflict-resolution rules
- NetworkX entity/evidence provenance graph
- schema-driven form requirements
AI & Retrieval
- AI-assisted semantic processing
- Retrieval-Augmented Generation (RAG)
- Pinecone vector retrieval
- ChromaDB vector retrieval
- ONNX Runtime
- MiniLM embeddings
- Gemini integration
- NetworkX knowledge graph
- Ragas faithfulness evaluation
- rubric-based LLM-as-judge groundedness checks
Data & Storage
- Neon PostgreSQL — production workflow and metadata persistence
- Supabase private object storage — uploaded documents, assets, and generated PDFs
- SQLite — local development where configured
Authentication & Security
- JWT-based authentication
- refresh-token authentication
- Google OAuth
- server-side resource ownership enforcement
- cross-user isolation
- upload validation
- CORS restrictions
- production configuration safeguards
- rate limiting on sensitive/expensive endpoints
Deployment
- Vercel — Next.js frontend
- Render — Dockerized FastAPI backend
- Neon — PostgreSQL
- Supabase — private object storage
Development
- Git
- GitHub
- OpenAI Codex
Codex was used as an engineering collaborator throughout development to accelerate implementation, debug document-processing and deployment issues, reason about PDF geometry, strengthen regression testing, investigate extraction failures, and harden the production system.
🚀 Running Locally
Prerequisites
Make sure the following are installed:
- Python 3.12+
- Node.js 20+
- npm
- Git
- Tesseract OCR
Clone the repository:
git clone <YOUR_REPOSITORY_URL>
cd knightforge-sahayak
1️⃣ Backend Setup
Navigate to the backend:
cd backend
Create a Python virtual environment:
python -m venv .venv
Windows PowerShell
.\.venv\Scripts\Activate.ps1
macOS / Linux
source .venv/bin/activate
Install dependencies:
pip install -r requirements.txt
Copy/configure the required environment variables using:
.env.example
Do not commit secrets or production credentials.

Run database migrations if required by your configuration:
alembic upgrade head
Start the FastAPI backend:
uvicorn app.main:app --reload --port 8000
The API should be available at:
http://127.0.0.1:8000
Verify backend health:
http://127.0.0.1:8000/health
FastAPI API documentation:
http://127.0.0.1:8000/docs
2️⃣ Frontend Setup
Open another terminal from the repository root:
cd frontend
Install dependencies:
npm install
Configure:
.env.local
For a local backend, the frontend API base URL should point to:
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
Start the development server:
npm run dev
Open:
http://localhost:3000
Keep both the frontend and backend running.
🧪 Testing & Evaluation
Golden-Sample Evaluation Harness
A Python evaluation harness was built around 100 golden KYC samples to assess structured extraction and the grounding of AI responses.
Metric	Reported Result	What It Measures
Precision	92%	Correct extracted field predictions relative to predicted fields
Recall	88%	Correct extracted field predictions relative to reference fields
F1 score	90%	Harmonic mean of precision and recall
Ragas faithfulness	0.89	Grounding of generated responses in retrieved context
Measured AI/retrieval latency	1.8 s → 650 ms	Before/after result from the project benchmark


The evaluation workflow also applies rubric-based LLM-as-judge scoring for groundedness and helps inspect schema failures, missing fields, incorrect extractions, conflicting evidence, and unsupported answers. The reported figures describe the project's evaluation setup and should not be treated as independent certification or production SLAs.
The exact harness entry-point/CLI is not specified in this README. Use the evaluation scripts present in the repository; do not assume a command name without checking the implementation.

Backend Regression Tests
From the backend directory, run the available end-to-end/regression suites:
python e2e_phase15.py
python e2e_phase16.py
python e2e_phase17.py
python e2e_phase18.py
Additional project-specific smoke or regression suites can be run according to the scripts available in the repository.
Frontend Type Check
cd frontend
npx tsc --noEmit
Frontend Lint
npm run lint
Production Build Verification
npm run build
A successful production build confirms that the Next.js application compiles correctly for deployment.
🔐 Security Design
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

AI is not the security boundary.
⚙️ Engineering Challenges
Several challenges required more than simply connecting an LLM to a PDF.
Different Form Layouts
Every KYC form has different geometry.

Solution: Form-specific placement manifests and schema-driven requirements.
False Extraction from Blank Forms
Printed labels can be mistaken for applicant data.

Solution: Region-aware extraction and validation rather than blindly accepting nearby text.
Partially Completed Forms
Existing user information should not be overwritten unnecessarily.

Solution: Non-destructive merge and placement rules.
Conflicting Documents
Multiple documents may provide different values.

Solution: Schema validation, confidence-aware conflict resolution, and NetworkX provenance traversal to connect selected fields to supporting documents and evidence.
Hallucination and Extraction Quality
LLM-generated answers can be weakly grounded, while OCR can misread document values.

Solution: A 100-sample Python evaluation harness measuring extraction precision/recall/F1, Ragas faithfulness, and rubric-based LLM-as-judge groundedness. Ambiguous or invalid structured values are flagged rather than automatically trusted.
Retrieval Latency
Embedding, retrieval, and generation can add significant response overhead.

Solution: Optimized the measured retrieval/AI path from 1.8 s to 650 ms in the project benchmark; real-world response times depend on input and runtime conditions.
Checkbox and Choice Fields
These cannot be handled like ordinary text fields.

Solution: Verified option rectangles and form-specific placement strategies.
Photos and Signatures
These are image assets rather than text fields.

Solution: Dedicated asset workflow with measured placement regions.
Cloud Persistence
Application state and uploaded documents must survive backend container replacement.

Solution: Persistent workflow data in PostgreSQL and private object storage for documents and generated assets.
Production Hardening
Several issues only appeared under real deployment conditions.

Solution: Production smoke testing, persistence verification, ownership-isolation testing, and regression-driven fixes.
⚠️ Deployment Notes
The public demo uses free-tier infrastructure.

The backend may require a short wake-up period after inactivity. OCR is also computationally intensive and processing time depends on document size, scan quality, and available compute.

These infrastructure constraints do not affect the core architecture and can be addressed in a production deployment using always-on compute, background processing, and scalable workers.
🔮 Future Improvements
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
- reproducible public benchmark scripts and documented evaluation datasets with sensitive values removed
- additional provenance-graph validation and explainability views
- expanded LLM-judge rubrics and evaluation coverage
🏆 Built For
OpenAI Build Week 2026

Developed as an individual project, KnightForge Sahayak explores how AI, retrieval, knowledge graphs, and deterministic document intelligence can work together to transform repetitive paperwork into a guided, understandable, and reusable workflow.

The project was built iteratively with OpenAI Codex supporting implementation, debugging, testing, architecture iteration, and engineering hardening.
⚠️ Disclaimer
KnightForge Sahayak is an AI-assisted paperwork tool built for demonstration and hackathon purposes.

It is not a substitute for official financial, legal, regulatory, or compliance advice.

Users should always review extracted information and generated documents before submitting them to any institution. Extraction metrics and faithfulness scores are specific to the test data and evaluation methodology used; they do not imply regulatory approval or guarantee field-level correctness for every document.
👨‍💻 Author
Prasad Nathe
📜 License
This project is intended for demonstration, educational, and hackathon purposes.
