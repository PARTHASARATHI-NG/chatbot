import sqlite3
from rapidfuzz import fuzz  # pip install rapidfuzz
import ollama
import re

# ========== DATABASE SETUP ==========
conn = sqlite3.connect("memory.db")
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS facts (
    question TEXT PRIMARY KEY,
    answer TEXT
)
""")
conn.commit()

# ========== FUNCTIONS ==========

def search_memory(user_input):
    """Search memory for similar questions (fuzzy match). Returns matched question and answer."""
    c.execute("SELECT question, answer FROM facts")
    rows = c.fetchall()
    for question, answer in rows:
        if fuzz.ratio(user_input.lower(), question.lower()) > 85:
            return question, answer
    return None, None

def save_memory(question, answer):
    """Save new fact to memory."""
    c.execute(
        "INSERT OR REPLACE INTO facts (question, answer) VALUES (?, ?)",
        (question, answer)
    )
    conn.commit()

def delete_memory(question):
    """Delete a fact from memory."""
    c.execute("DELETE FROM facts WHERE question = ?", (question,))
    conn.commit()

def ask_llm(prompt):
    """Ask the local LLM with instruction to answer short first."""
    system_prompt = (
        "You are a helpful assistant. "
        "Answer briefly in one sentence first. "
        "If the user wants more details, provide a longer explanation."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    response = ollama.chat(
        model="phi3",
        messages=messages
    )
    return response["message"]["content"].strip()

def split_answer(answer_text):
    """Split answer into short (first sentence) and detailed (rest), trimming leading punctuation from detail."""
    if not answer_text:
        return "", ""

    # Find first sentence-ending punctuation (., !, ?) using regex
    match = re.search(r'[.?!]', answer_text)
    if not match:
        return answer_text, ""

    split_index = match.end()
    short = answer_text[:split_index].strip()
    detail = answer_text[split_index:].strip()

    # Remove leading punctuation or whitespace from detail to avoid '.' or ';' start
    detail = re.sub(r'^[\s.;,:-]+', '', detail)
    return short, detail

def wants_more_details(user_input):
    """Simple check if user input means 'yes, give me more details'."""
    yes_keywords = ['yes', 'sure', 'more', 'tell me', 'explain', 'detail', 'please', 'yeah', 'yep', 'ok', 'okay']
    input_lower = user_input.lower()
    return any(word in input_lower for word in yes_keywords)

def chunk_text(text, max_length=300):
    """Split text into chunks of approx max_length chars without cutting sentences and skipping empty ones."""
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?]) +', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue  # skip empty sentences

        # Check if adding this sentence exceeds max_length
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
        else:
            chunks.append(current_chunk)
            current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

# ====== DIALOG MANAGEMENT =======
last_answer_detail_chunks = []  # Store detailed chunks for follow-up
last_answer_index = 0  # Index of which chunk to send next

# ========== MAIN LOOP ==========
print("🤖 Self-Learning Chatbot (type 'exit' to quit, 'delete <question>' to remove fact)")

while True:
    user_input = input("You: ").strip()

    if user_input.lower() == "exit":
        break

    # Handle deletion command
    if user_input.lower().startswith("delete "):
        q_to_delete = user_input[7:].strip()
        delete_memory(q_to_delete)
        print(f"🗑 Deleted fact about: '{q_to_delete}'")
        continue

    # Handle "want more details" during detail chunk delivery
    if last_answer_detail_chunks and wants_more_details(user_input):
        if last_answer_index < len(last_answer_detail_chunks):
            print(f"Bot (detail): {last_answer_detail_chunks[last_answer_index]}")
            last_answer_index += 1
            if last_answer_index == len(last_answer_detail_chunks):
                # Finished all chunks
                last_answer_detail_chunks = []
                last_answer_index = 0
            else:
                print("Bot: Would you like to hear more?")
        else:
            # No more chunks
            last_answer_detail_chunks = []
            last_answer_index = 0
        continue

    # If user says no or unrelated after asking for more details
    if last_answer_detail_chunks and user_input.lower() in ["no", "nah", "nope", "not now"]:
        print("Bot: Okay, let me know if you want to learn something else!")
        last_answer_detail_chunks = []
        last_answer_index = 0
        continue

    # Search in memory
    matched_question, answer = search_memory(user_input)
    if answer:
        print(f"Bot (Memory): {answer}")
        # Memory answers given as-is, no chunking or split
        last_answer_detail_chunks = []
        last_answer_index = 0
        continue

    # Ask LLM if not found in memory
    answer = ask_llm(user_input)

    # Split into short + detail
    short, detail = split_answer(answer)

    # Store detailed chunks if any
    if detail:
        last_answer_detail_chunks = chunk_text(detail, max_length=300)
        last_answer_index = 0
        print(f"Bot (LLM): {short} Would you like to hear more?")
    else:
        last_answer_detail_chunks = []
        last_answer_index = 0
        print(f"Bot (LLM): {short}")

    # Ask if correct and save
    correct = input("Is this correct? (y/n): ").strip().lower()
    if correct == "y":
        full_answer = f"{short} {detail}".strip()
        save_memory(user_input, full_answer)
        print("✅ Saved to memory.")
    elif correct == "n":
        correct_answer = input("Please provide the correct answer: ").strip()
        save_memory(user_input, correct_answer)
        print("✅ Correct answer saved.")
