# vector
Project: AI Trading Assistant

Goal: Build a smart, desktop-based AI assistant that helps traders and developers interact with large codebases and documents using natural language — while keeping memory private and code edits test-safe.

🏗️ 1. OVERALL ARCHITECTURE
Layer	Technology
GUI	Python + Tkinter
Embedding Engine	sentence-transformers (MiniLM)
Vector DB	FAISS (local)
LLM API	OpenAI gpt-4-turbo or gpt-5.2
File Ingestion	.txt, .pdf, .md, .py (comments only)
Code Indexing	Full directory scan (multi-subfolder)
File Editing	GPT-assisted editing with rollback
Test Framework	pytest, unittest, or custom command
Memory Storage	knowledge_base/, embedded + indexed
🔧 2. CORE MODULES AND FILES
File	Purpose
app.py	Launches GUI and connects user inputs to assistant backend
assistant.py	Main chat engine + GPT API integration
memory_engine.py	Handles file chunking, embedding, indexing, and retrieval
file_handler.py	Handles drag-and-drop, recursive indexing, and file edits
editor_engine.py	Performs code transformation + safe rollback
test_runner.py	Runs tests before/after edits
config.py	Stores paths, test commands, model config
requirements.txt	Project dependencies
README.md	Full project overview
gui_upgrades.py	(Optional) Modular enhancements to GUI features
🧩 3. KEY FEATURES AND FUNCTIONS
📁 File Ingestion and Knowledge Base

Drag and drop files/folders into GUI

Recursively scan directory and subdirectories

Supported formats:

.txt, .md → Raw text

.pdf → Parsed using pdfminer.six

.py → Extracts only comments for semantic memory

Save all to knowledge_base/

Chunk files into overlapping 500-token blocks

Embed chunks using MiniLM and store with path metadata in FAISS

🧠 Memory and Querying

When a question is asked:

Embed query locally

Use FAISS to get top-k relevant document chunks

Inject these into the GPT prompt

GPT answers using both memory + question

Enable/disable memory via checkbox

Cycle between alternate top-k memory chunks (rotation)

Debug view shows what memory was used

📝 Note-to-Memory Capture

Input box for user notes (e.g. ideas, learnings)

Saves to knowledge_base/note_xyz.txt

Can reindex immediately

💬 Chat Functionality

GUI textbox for query

Scrollable output box for GPT responses

Option to save query + response as .txt or .md

📊 Token Usage Display

Shows:

Input token count

Output token count

Estimated cost

Uses OpenAI pricing model per model (e.g. $0.01/$0.03 per 1K tokens)

📂 Codebase Indexing and Editing

Select root directory

Recursively index:

File path

File type

Contents split into semantically meaningful chunks

Map file paths to vector memory

Ask natural language questions like:

“Find all files that import db.py and rename connect() to connect_db()”

✏️ Code Editing Flow

Based on retrieved memory, assistant suggests code changes

For each file:

Load original

Apply GPT transformation

Save to temp (or diff display)

Validate with tests

Only overwrite original if tests pass

🧪 Safe Code Refactor with Testing

Run tests before and after code edits

Tests can be:

pytest

unittest

Custom shell command

If post-edit tests fail:

File is restored to original

Error logged

🔃 Reindexing

One-click reindex memory button

Re-embeds all current files in knowledge_base/

Updates FAISS vector index

🖥️ 4. GUI Layout (Tkinter)
Top Controls:

Folder selector ([ Choose Directory ])

Checkbox: [✓] Use Memory

Buttons: Reindex, Cycle Memory, Save Chat, Clear Output

Main Window:
Section	Function
Query Input	User types natural language
Response Output	Scrollable GPT reply area
Memory Viewer	Show chunks retrieved for this query
Notes Section	Enter custom text to add to memory
Token Display	Live token + cost tracker
Status Bar	Show active file, test results, etc.
🔒 5. Privacy and Cost Efficiency
Layer	Local	Cloud
File parsing	✅	❌
Embeddings	✅ (MiniLM)	❌
Vector search	✅ (FAISS)	❌
LLM response	❌ (OpenAI GPT-4)	✅
Test runner	✅	❌

Only small prompt + memory chunks are sent to OpenAI.
No files or full docs ever leave your machine.

🚦 6. Deployment Options
Method	Tools
Run from source	python app.py
Standalone .exe	Use pyinstaller with --onefile flag
GitHub Repo	Structured with README, license, versioned releases
🛠 7. Dependencies (requirements.txt)
openai
sentence-transformers
faiss-cpu
PyPDF2
pdfminer.six
python-docx
openpyxl
python-pptx
pyyaml
tk
matplotlib
pytest

🧠 8. Smart Query Examples

These are the types of prompts the assistant can handle naturally:

“What is a Wyckoff spring?”

“Update all Python files that import logger.py to use log_v2().”

“Refactor my strategy.py file to remove global variables.”

“Find the file where get_order_book() is defined.”

“Add error handling to all files that open files using open().”

“What does my market_analysis.pdf say about liquidity zones?”

✅ Summary

This assistant acts as:

📖 A memory-aware document researcher

👨‍💻 A coding co-pilot with file editing powers

💡 A trading system design brainstormer

🔬 A safe, test-verified code editor

🧠 A GPT-powered assistant that understands your own materials
