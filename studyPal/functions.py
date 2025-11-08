import uuid
import hashlib
from firebase_admin import firestore
import json
import re

# -------------------------
# User functions
# -------------------------
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_user_id():
    return str(uuid.uuid4())

def create_user(db, name, email, password):
    user_id = generate_user_id()
    users_ref = db.collection("users")
    users_ref.document(user_id).set({
        "name": name,
        "email": email,
        "password": hash_password(password),
        "createdAt": firestore.SERVER_TIMESTAMP
    })
    return user_id, f"User {name} created."

def login_user(db, email, password):
    users_ref = db.collection("users")
    query = users_ref.where("email", "==", email).limit(1).get()
    if not query:
        return False, "User not found", None
    user = query[0]
    stored_hash = user.to_dict()["password"]
    if stored_hash == hash_password(password):
        return True, f"Welcome {user.to_dict()['name']}", user.id
    else:
        return False, "Incorrect password", None


# -------------------------
# AI functions
# -------------------------
def aiSummariser(text, client):
        model = "gpt-4o-mini",
        prompt=f"""
            Summarize the following text for revision. 
    
            Structure the output as clean, semantic HTML.
            - Use <h3> tags for main topics or keywords.
            - Use <p> tags for explanations.
            - Use <ul> and <li> tags for any lists.
            - Use <strong> tags for key terms within a paragraph.
            
            Do not include any text outside of this HTML structure (like "Here is your summary...").
            Do not include <html>, <head>, or <body> tags. Only provide the HTML fragment for the body content.

            Text to summarize: {text}"""
        messages_list = [
            # Message 0: The System Role (must be a dictionary)
            {"role": "system", "content": "You are a helpful study assistant that formats notes perfectly in HTML."},
            
            # Message 1: The User Prompt (must be a dictionary)
            {"role": "user", "content": prompt}
        ]

        response = client.chat.completions.create(
            model="gpt-4o-mini", # Using gpt-4o-mini as in your example
            messages=messages_list
        )
        
        # Get the raw HTML content
        html_summary = response.choices[0].message.content.strip()
        
        # A small cleanup to remove potential markdown code fences
        # sometimes the AI wraps its HTML output in ```html ... ```
        if html_summary.startswith("```html"):
            html_summary = html_summary[7:] # Remove "```html\n"
        if html_summary.endswith("```"):
            html_summary = html_summary[:-3] # Remove "```"
            
        return html_summary.strip()


# ------------------------------------
# Notes/Summariations functions
# ------------------------------------

def save_note(db, user_id, original_text, summary_text, title):
    note_id = str(uuid.uuid4())
    notes_ref = db.collection("notes").document(note_id)
    notes_ref.set({
        "user_id": user_id,
        "original_text": original_text,
        "summary_text": summary_text,
        "title": title,
        "timestamp": firestore.SERVER_TIMESTAMP
    })
    return note_id

def get_notes(db, user_id):
    """
    Retrieve all notes for a specific user.
    """
    notes_ref = db.collection("notes")
    docs = notes_ref.where("user_id", "==", user_id).stream()
    return [
        {"note_id": doc.id, **doc.to_dict()}
        for doc in docs
    ]

def update_note(db, note_id, original_text=None, summary_text=None):
    """
    Update a note's text and/or summary.
    """
    notes_ref = db.collection("notes").document(note_id)
    updates = {}
    if original_text:
        updates["original_text"] = original_text
    if summary_text:
        updates["summary_text"] = summary_text
    if updates:
        notes_ref.update(updates)
        return True
    return False

def delete_note(db, note_id):
    """
    Delete a specific note by note_id.
    """
    notes_ref = db.collection("notes").document(note_id)
    notes_ref.delete()

# --------------------------------
#flashcard functions
# --------------------------------
def generate_flashcards(db, user_id, note_id, summary_text, client):
    # 1. Define the detailed prompt structure
    prompt = (
        f"Generate 5 high-quality, concise flashcards from the following summarized study text.\n\n"
        "Each flashcard must test a core concept, key term, or essential function from the text.\n"
        "Specifically, ensure you include:\n"
        "a) At least one **definition** card (e.g., 'What is X?').\n"
        "b) At least one **example/function** card (e.g., 'Give an example of Y.').\n"
        "c) At least one card focusing on a **scheduling algorithm** or **OS type**.\n\n"
        f"Text to analyze:\n---\n{summary_text}\n---\n\n"
        "Return the result STRICTLY as a valid JSON array of objects. Do not include any introductory or concluding text. "
        "The objects must have only two keys: 'question' (the question) and 'answer' (the direct answer)."
    )

    # 2. Make the API call
    response = client.chat.completions.create(
        # Swapping to gpt-4o-mini is good for cost/speed, but sometimes gpt-4
        # is better at strictly following complex JSON output rules.
        model="gpt-4o-mini",
        messages=[
            # System content is optimized to enforce the JSON output
            {"role": "system", "content": "You are a helpful study assistant. Your ONLY output must be a valid, parsable JSON array of flashcard objects, each with 'question' and 'answer' keys. Do not output any markdown code fences (```json) or text."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip()


def get_flashcards(db, user_id, note_id):
    """Fetches the flashcards list directly from the note document."""
    
    note_doc = db.collection("notes").document(note_id).get()
    
    if note_doc.exists:
        note_data = note_doc.to_dict()
        # Retrieve the 'flashcards' field, default to an empty list if not found
        cards = note_data.get("flashcards", [])
        return cards
    
    return []

