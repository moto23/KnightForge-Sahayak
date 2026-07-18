# ⚔️ KnightForge Sahayak

### AI-Assisted KYC Paperwork Copilot

KnightForge Sahayak turns complex KYC paperwork into a guided, intelligent workflow.

Upload a supported KYC form and supporting documents. Sahayak automatically classifies documents, extracts and merges relevant information, tracks what is still missing, guides the user through remaining fields, validates the data, and generates a completed version of the uploaded KYC form.

Built for **OpenAI Build Week 2026**.

---

## 🎬 Demo

🌐 **Live Demo:** <YOUR_DEPLOYED_URL>

▶️ **Demo Video:** <YOUR_DEMO_VIDEO_URL>

---

## ✨ Features

- 📄 **Multi-Form KYC Support** — CVL/CDSL, SBI, HDFC, ICICI and Axis
- 🔍 **Automatic Document Classification** — Detects KYC forms and supporting documents
- 🧠 **Smart Extraction & Prefill** — Extracts information from PAN, Aadhaar, Passport, Driving Licence, bank statements and other KYC evidence
- 👤 **Canonical Profile** — Merges information from multiple documents with confidence and provenance tracking
- ⚖️ **Conflict Resolution** — Detects conflicting information across documents instead of silently guessing
- 💬 **AI-Guided Completion** — Asks only for genuinely missing or unresolved information
- 📊 **Progress Tracking** — Dynamically tracks completion based on the active KYC form
- ✅ **Deterministic Validation** — Validates structured fields such as PAN, Aadhaar and PIN codes
- 🖼️ **Photo & Signature Support** — Handles required applicant photos and signatures where supported by the form
- 📑 **Smart PDF Generation** — Completes a copy of the user's uploaded primary KYC form while preserving existing content
- 🕘 **PDF Version History** — Preview, edit and save updated versions without modifying previous PDFs
- 📚 **Knowledge Chat** — KYC-focused assistance powered by a trusted knowledge base with grounded answers and citations

---

## 🔄 How It Works

1. **Upload Primary Form** — Select or upload a supported KYC form.
2. **Add Supporting Documents** — Upload one or multiple identity/address documents.
3. **Extract & Merge** — Sahayak reads available information and builds a unified Canonical Profile.
4. **AI-Guided Completion** — Answer only the fields that are genuinely missing or need resolution.
5. **Validate & Review** — Review your information and completion progress.
6. **Generate PDF** — Create and preview a completed copy of your uploaded KYC form.

---

## 🛠️ Tech Stack

### Frontend

- Next.js
- TypeScript
- Tailwind CSS

### Backend

- FastAPI
- Python
- SQLite

### AI & Document Intelligence

- Gemini
- OCR
- BGE Embeddings
- RAG
- Semantic Extraction

### Document Processing

- PyMuPDF
- Pillow
- Tesseract OCR
- Schema-driven PDF placement

---

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd knightforge-sahayak
```

### 2. Start the Backend

```bash
cd backend
python -m venv .venv
```

**Windows:**

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure the required environment variables using the provided `.env.example`, then start the API:

```bash
uvicorn app.main:app --reload
```

Backend:

```text
http://127.0.0.1:8000
```

### 3. Start the Frontend

Open a new terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend:

```text
http://localhost:3000
```

---

## 🧪 Testing

### Backend Tests

From the `backend` directory, run the available regression suites:

```bash
python e2e_phase15.py
python e2e_phase16.py
python e2e_phase17.py
python e2e_phase18.py
```

### Frontend Verification

```bash
cd frontend
npm run lint
npm run build
```

---

## 📂 Supported Primary KYC Forms

| Form | Support |
|---|---|
| CVL / CDSL KYC | ✅ |
| SBI KYC Updation — Annexure A | ✅ |
| HDFC KYC | ✅ |
| ICICI KYC | ✅ |
| Axis KYC | ✅ |

The application also provides tested blank KYC templates that users can view and download directly from the Upload page.

---

## 🔐 Important Note

KnightForge Sahayak is an AI-assisted paperwork tool and should not be treated as a substitute for official financial, legal or compliance advice.

Users should review all generated information and the completed PDF before submission.

---

## 🏆 Built For

**OpenAI Build Week 2026**

Built with the goal of making complex paperwork easier to understand, complete and verify through a combination of document intelligence, deterministic validation and AI-guided assistance.

---

## 👨‍💻 Author

**Prasad Nathe**

---

## 📜 License

This project is intended for demonstration and hackathon purposes.
