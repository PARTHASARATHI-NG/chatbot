import sqlite3
from rapidfuzz import fuzz  # pip install rapidfuzz
import ollama
import re
import random

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

    match = re.search(r'[.?!]', answer_text)
    if not match:
        return answer_text, ""

    split_index = match.end()
    short = answer_text[:split_index].strip()
    detail = answer_text[split_index:].strip()
    detail = re.sub(r'^[\s.;,:-]+', '', detail)
    return short, detail

def wants_more_details(user_input):
    """Check if user input means 'yes, give me more details'."""
    yes_keywords = [
        'yes', 'sure', 'more', 'tell me', 'explain', 'detail',
        'please', 'yeah', 'yep', 'ok', 'okay', 'go on', 'elaborate'
    ]
    input_lower = user_input.lower()
    return any(word in input_lower for word in yes_keywords)

def wants_stop_details(user_input):
    """Check if user input means 'no, don’t give more details'."""
    no_keywords = [
        'no', 'nah', 'nope', 'not now', 'thanks', 'enough',
        'that’s enough', 'stop', 'quit', 'done', 'fine', 'ok', 'okay'
    ]
    input_lower = user_input.lower()
    return any(word in input_lower for word in no_keywords)

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
            continue

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

# ===== Local random stop responses =====
STOP_RESPONSES = [
    "Alright, feel free to ask me anything else!",
    "Got it! I'm here if you want to learn more.",
    "Sure, we can move on to another topic.",
    "Okay, let me know if you want to explore something else.",
    "Understood! Ready for your next question whenever you are."
]

def get_stop_detail_response():
    """Return a random friendly stop message from predefined list."""
    return random.choice(STOP_RESPONSES)

# ===== Greeting Detection =====
GREETINGS = ["hi", "hello", "hey", "bye", "goodbye", "see you", "good night", "good morning"]

def is_greeting(user_input):
    """Check if input is a simple greeting or farewell."""
    input_lower = user_input.lower().strip()
    return any(input_lower.startswith(word) or input_lower == word for word in GREETINGS)

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
                last_answer_detail_chunks = []
                last_answer_index = 0
            else:
                print("Bot: Would you like to hear more?")
        else:
            last_answer_detail_chunks = []
            last_answer_index = 0
        continue

    # Handle stop detail responses dynamically
    if last_answer_detail_chunks and wants_stop_details(user_input):
        dynamic_stop_msg = get_stop_detail_response()
        print(f"Bot: {dynamic_stop_msg}")
        last_answer_detail_chunks = []
        last_answer_index = 0
        continue

    # ===== Memory retrieval with dynamic paraphrase =====
    matched_question, stored_answer = search_memory(user_input)
    if stored_answer:
        paraphrased_answer = ask_llm(f"Paraphrase this in your own words: {stored_answer}")
        short, detail = split_answer(paraphrased_answer)

        if detail and not is_greeting(user_input):  # 👈 skip "Would you like more?" for greetings
            last_answer_detail_chunks = chunk_text(detail, max_length=300)
            last_answer_index = 0
            print(f"Bot (Memory): {short} Would you like to hear more?")
        else:
            last_answer_detail_chunks = []
            last_answer_index = 0
            print(f"Bot (Memory): {short}")
        continue

    # ===== Ask LLM for new question =====
    answer = ask_llm(user_input)
    short, detail = split_answer(answer)

    if detail and not is_greeting(user_input):  # 👈 skip "Would you like more?" for greetings
        last_answer_detail_chunks = chunk_text(detail, max_length=300)
        last_answer_index = 0
        print(f"Bot (LLM): {short} Would you like to hear more?")
    else:
        last_answer_detail_chunks = []
        last_answer_index = 0
        print(f"Bot (LLM): {short}")

    # ===== Ask if correct and save (first-time learning only) =====
    correct = input("Is this correct? (y/n): ").strip().lower()
    if correct == "y":
        full_answer = f"{short} {detail}".strip()
        save_memory(user_input, full_answer)
        print("✅ Saved to memory.")
    elif correct == "n":
        correct_answer = input("Please provide the correct answer: ").strip()
        save_memory(user_input, correct_answer)
        print("✅ Correct answer saved.")
