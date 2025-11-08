from flask import Flask, render_template, request, redirect, url_for, session
import os
import random
import firebase_admin
import json
from firebase_admin import credentials, firestore, storage
from openai import OpenAI
from functions import create_user, login_user, aiSummariser, save_note, generate_flashcards, get_flashcards
from dotenv import load_dotenv 
from pypdf import PdfReader
from docx import Document
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


load_dotenv()

# -------------------------
# Initialize Firebase
# -------------------------
json_str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

if json_str:
    # Load from GitHub Secret / env var
    service_account_info = json.loads(json_str)
    cred = credentials.Certificate(service_account_info)
elif os.path.exists("adminKey.json"):
    # Local fallback (optional)
    cred = credentials.Certificate("adminKey.json")
else:
    raise RuntimeError(
        "Service account credentials not set. "
        "Set GOOGLE_APPLICATION_CREDENTIALS_JSON or provide adminKey.json."
    )

firebase_admin.initialize_app(cred)
db = firestore.client()
bucket = storage.bucket('studypal-93412.firebasestorage.app')  # <-- Specify bucket name explicitly

# -------------------------
# Initialize OpenAI
# -------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------------
# Initialize Flask
# -------------------------
app = Flask(__name__)
app.secret_key = "supper_secret_key"
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB max upload size

# -------------------------
# Routes
# -------------------------
@app.route("/")
def home():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    notes_ref = db.collection("notes").where("user_id", "==", user_id)
    notes = [dict(doc.to_dict(), note_id=doc.id) for doc in notes_ref.stream()]
    return render_template("home.html", notes=notes)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        create_user(db, name, email, password)
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        success, _, user_id = login_user(db, email, password)
        if success:
            session["user_id"] = user_id
            return redirect(url_for("home"))
        return "Login failed"

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))


@app.route("/flashcards/<note_id>")
def flashcards(note_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    cards = get_flashcards(db, user_id, note_id)
    return render_template("flashcards.html", flashcards=cards, note_id=note_id)


@app.route("/Note/<note_id>")
def viewNote(note_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    note_doc = db.collection("notes").document(note_id).get()
    if note_doc.exists:
        note_data = note_doc.to_dict()
        note_data['note_id'] = note_id  # <-- Add note_id for template links
    else:
        note_data = None

    return render_template("note.html", note=note_data)


@app.route("/edit_note", methods=["GET", "POST"])
def edit_note():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title", "Untitled")
        text = request.form["notes"]
        action = request.form.get("action")

        if action == "save":
            note_id = save_note(db, user_id, text, None, title)
            generate_flashcards(db, user_id, note_id, text, client)
            return redirect(url_for("home"))

        if action == "summarise":
            summary = aiSummariser(text, client)
            return render_template("write.html", summary=summary, user_id=user_id, title=title, content=text)

    return render_template("write.html", user_id=user_id)


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    return "File too large. Maximum allowed size is 10 MB.", 413


# -------------------------
# Upload Document Route
# -------------------------
@app.route("/upload_doc", methods=["GET", "POST"])
def upload_doc():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        title = request.form.get("title", "Untitled")
        file = request.files.get("document")
        if not file or action != "save":
            return "No file uploaded or action not save", 400

        extension = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{user_id}_{random.randint(1000,9999)}_{secure_filename(file.filename)}"

        blob = bucket.blob(f"notes/{filename}")
        file.stream.seek(0) # IMPORTANT: Reset stream for upload
        blob.upload_from_file(file)
        blob.make_public()
        file_url = blob.public_url

        text = ""
        file.stream.seek(0) # IMPORTANT: Reset stream for text extraction
        if extension == 'pdf':
            reader = PdfReader(file)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif extension == 'docx':
            reader = Document(file)
            for para in reader.paragraphs:
                text += para.text + "\n"
        else:
            return "Unsupported file type", 400

        # Save initial note and get note_id
        note_id = save_note(db, user_id, text, None, title) 

        # Generate summary & flashcards
        summary = ""
        flashcards = [] # <-- Initialization for accumulation
        
        # Safer chunk size for API processing
        chars_per_chunk = 40000 
        start = 0
        
        while start < len(text):
            chunk = text[start:start + chars_per_chunk]
            
            # 1. Generate Summary (HTML)
            chunk_summary = aiSummariser(chunk, client)
            summary += chunk_summary + "\n"

            # 2. Generate Flashcards (JSON String)
            json_string = generate_flashcards(db, user_id, note_id, chunk_summary, client)
            
            # CRITICAL: Parse the JSON and accumulate the cards
            try:
                cards_list = json.loads(json_string) 
                flashcards.extend(cards_list)
            except json.JSONDecodeError as e:
                print(f"Error parsing flashcards JSON for chunk starting at {start}: {e}")
                # Log the faulty JSON output for debugging
                # print(f"Faulty JSON: {json_string}") 
                pass # Continue processing the next chunk if one fails
                
            start += chars_per_chunk

        # Update Firestore with file URL, full summary, AND flashcards
        db.collection("notes").document(note_id).update({
            "original_text": file_url,
            "summary_text": summary,
            "flashcards": flashcards # <-- Saving the complete list
        })

        return redirect(url_for("home"))

    return render_template("upload.html", user_id=user_id)

# -------------------------
# Download Route (redirects to Storage file)
# -------------------------
@app.route("/Note/<note_id>/download")
def downloadNote(note_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    note_doc = db.collection("notes").document(note_id).get()
    if not note_doc.exists:
        return "Note not found", 404

    note_data = note_doc.to_dict()
    file_url = note_data.get("original_text")

    if file_url and file_url.startswith("http"):
        return redirect(file_url)  # <-- Redirects user to download the actual file
    return "No file associated with this note.", 404


# -------------------------
# Run App
# -------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

# Health Check
def health():
    return "ok"
