import json
import os
import re
import webbrowser
from datetime import datetime
from threading import Timer
from flask import Flask, jsonify, render_template, request, send_from_directory
from groq import Groq

app = Flask(
    __name__,
    template_folder='.',
    static_folder='.'
)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

def init_groq_client():
    if not GROQ_API_KEY:
        return None
    try:
        return Groq(api_key=GROQ_API_KEY)
    except Exception as exc:
        # Keep the web service alive even if SDK deps are incompatible in deploy env.
        print(f"Warning: Groq client disabled at startup: {exc}")
        return None

client = init_groq_client()

PORT = int(os.environ.get("PORT", 5001))

state = {
    "current_step": "Landing",
    "selected_day": "Monday",
    "user_profile": {},
    "weekly_routine": {},
    "messages": [],
    "mood_history": [],
    "journal_entries": [],
    "meds": []
}


def build_fallback_chat_response(user_msg, profile, messages):
    """Return a warm, contextual response when the LLM is unavailable."""
    text = str(user_msg or "").strip()
    lowered = text.lower()

    def has_word(haystack, word):
        return bool(re.search(rf"\b{re.escape(word)}\b", haystack))

    def has_any_words(haystack, words):
        return any(has_word(haystack, word) for word in words)

    challenges = str(profile.get("challenges", "")).strip()
    mood = str(profile.get("mood", "Neutral")).strip() or "Neutral"

    if not text:
        return "I am here with you. What is on your mind right now?"

    if has_any_words(lowered, ["hi", "hello", "hey"]):
        return "I am glad you are here. How are you feeling in this moment?"

    if has_any_words(lowered, ["thank", "thanks"]):
        return "You are very welcome. What feels most important for us to focus on next?"

    assistant_messages = [m for m in (messages or []) if m.get("role") == "assistant"]
    last_assistant = str(assistant_messages[-1].get("content", "")).strip() if assistant_messages else ""

    user_messages = [m for m in (messages or []) if m.get("role") == "user"]
    turn_number = len(user_messages)
    recent_user_context = " ".join(
        str(m.get("content", "")).lower() for m in user_messages[-4:]
    )

    asks_for_tip = any(
        phrase in lowered
        for phrase in [
            "tip",
            "tips",
            "advice",
            "guidance",
            "suggest",
            "recommend",
            "help me",
            "what should i do",
            "how do i",
            "how to",
            "what can i do"
        ]
    )

    asks_for_more_help = any(
        phrase in lowered
        for phrase in ["more", "another", "else", "further", "continue"]
    ) and asks_for_tip

    if asks_for_more_help:
        return (
            "Yes. Here is another gentle option: do 4 rounds of box breathing, "
            "then write one supportive sentence to yourself like I am safe right now. "
            "Would you like a short morning routine too?"
        )

    if asks_for_tip and any(word in recent_user_context for word in ["sad", "down", "anxious", "stress", "worried"]):
        return (
            "I can help with that. Try this now: place one hand on your chest, take 5 slow breaths, "
            "then do one small comforting action like warm tea or a short walk. "
            "Would you like a 2 minute plan or a 10 minute plan?"
        )

    if asks_for_tip:
        return (
            "Absolutely. A simple next step is to pick one tiny action you can finish in 5 minutes, "
            "then check in with your body and mood after. "
            "Would you like me to suggest one based on how you feel right now?"
        )

    short_response = len(text.split()) <= 4
    short_topic = text.rstrip(".,!?;:")

    if short_response and has_any_words(lowered, ["breathing", "breath"]):
        return (
            "Great choice. Try this with me now: inhale for 4, hold for 4, exhale for 6, and repeat 5 times. "
            "After that, tell me if your body feels even a little calmer."
        )

    if short_response and "comfort" in last_assistant.lower():
        return (
            f"{short_topic.capitalize()} can be a real source of comfort. "
            "Would you like to make that your support step for today, and pair it with a short breathing break?"
        )

    if short_response and "next hour" in last_assistant.lower():
        return (
            f"That is a good choice. Let us make it gentle and doable: start with {short_topic.lower()} for 10 minutes, "
            "then pause and notice if your mood feels even slightly lighter."
        )

    topic_prompts = [
        (["anxious", "anxiety", "worried", "stress", "overwhelm"],
         "That sounds really heavy. Would a 2 minute breathing reset feel doable right now, or would you rather talk it through first?"),
        (["sad", "down", "depressed", "hopeless"],
         "Thank you for sharing that with me. What is one small thing that usually gives you even a little comfort?"),
        (["angry", "frustrated", "irritated"],
         "I hear the frustration. What happened today that felt hardest to handle?"),
        (["sleep", "tired", "exhausted", "fatigue"],
         "Low energy can make everything harder. Would it help to choose one gentle task for the next hour together?"),
        (["lonely", "alone", "isolated"],
         "Feeling alone can be painful. Is there one person you would feel okay checking in with today?"),
        (["pain", "hurt", "ache"],
         "I am sorry you are dealing with that discomfort. Would you like to adjust today to gentler activities?"),
    ]

    for keywords, response in topic_prompts:
        if has_any_words(lowered, keywords):
            return response

    response_options = []

    if challenges:
        response_options.append(
            f"I hear you. Since you mentioned {challenges} earlier, how is that showing up for you right now?"
        )

    response_options.extend([
        "Thank you for telling me that. What part of this feels hardest at the moment?",
        "I am with you. If we focused on just one small next step, what would feel most doable?",
        f"You seem to be feeling {mood.lower()} today. What kind of support would feel best right now?"
    ])

    response = response_options[(turn_number - 1) % len(response_options)]

    if last_assistant and response == last_assistant:
        response = "I hear you. What is one thing you need most right now: calm, energy, or encouragement?"

    return response


def normalize_medication(item):
    """Normalize legacy and new med entries into one stable API shape."""
    med_name = str(item.get("name") or item.get("Medicine") or "").strip()
    med_time = str(item.get("time") or item.get("Time") or "").strip()
    med_id = str(item.get("id") or f"med-{datetime.now().timestamp()}")
    taken_value = item.get("taken") if "taken" in item else item.get("Taken", False)
    return {
        "id": med_id,
        "name": med_name,
        "time": med_time,
        "taken": bool(taken_value)
    }

def clean_hobbies(raw_hobbies):
    if not raw_hobbies or not isinstance(raw_hobbies, str):
        return "Your Favorite Hobby"
    
    text = raw_hobbies.strip()
    
    # Strip out common introductory filler phrases
    prefix_patterns = [
        r'^(i\s+enjoy|i\s+like|i\s+love|my\s+hobbies\s+are|my\s+hobby\s+is|i\s+prefer|i\s+do|enjoying|liking)\s+'
    ]
    for pattern in prefix_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Normalize ' and ' into commas for uniform splitting
    text = re.sub(r'\s+and\s+', ', ', text, flags=re.IGNORECASE)
    
    # Split by commas or semicolons
    raw_items = [item.strip() for item in re.split(r'[,;]+', text) if item.strip()]
    
    cleaned_items = []
    for item in raw_items:
        # Strip non-alphanumeric characters from start/end
        item = re.sub(r'^[^\w]+|[^\w]+$', '', item)
        # Remove filler words within individual items if present
        item = re.sub(r'^(i\s+enjoy|i\s+like|i\s+love)\s+', '', item, flags=re.IGNORECASE).strip()
        if item:
            cleaned_items.append(item.title())

    if not cleaned_items:
        return "Your Favorite Hobby"
    elif len(cleaned_items) == 1:
        return cleaned_items[0]
    elif len(cleaned_items) == 2:
        return f"{cleaned_items[0]} & {cleaned_items[1]}"
    else:
        return f"{', '.join(cleaned_items[:-1])} & {cleaned_items[-1]}"


def extract_hobbies_list(raw_hobbies):
    """
    Parses user hobby input and returns a list of cleaned, individual hobby titles.
    Example input: "I enjoy reading, chess, and gardening"
    Output: ["Reading", "Chess", "Gardening"]
    """
    if not raw_hobbies or not isinstance(raw_hobbies, str):
        return ["your favorite hobby"]

    text = raw_hobbies.strip()

    # Strip common introductory phrases
    prefix_patterns = [
        r'^(i\s+enjoy|i\s+like|i\s+love|my\s+hobbies\s+are|my\s+hobby\s+is|i\s+prefer|i\s+do|enjoying|liking)\s+'
    ]
    for pattern in prefix_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # Convert ' and ' into commas
    text = re.sub(r'\s+and\s+', ', ', text, flags=re.IGNORECASE)

    # Split by comma or semicolon
    raw_items = [item.strip() for item in re.split(r'[,;]+', text) if item.strip()]

    cleaned_items = []
    for item in raw_items:
        # Strip leading/trailing non-alphanumeric chars
        item = re.sub(r'^[^\w]+|[^\w]+$', '', item)
        item = re.sub(r'^(i\s+enjoy|i\s+like|i\s+love)\s+', '', item, flags=re.IGNORECASE).strip()
        if item:
            cleaned_items.append(item.title())

    return cleaned_items if cleaned_items else ["your favorite hobby"]


def extract_primary_household_task(raw_household):
    """
    Returns one cleaned household task string.
    - If no input is provided, returns an empty string.
    - If input is provided, strips filler and returns only the core answer.
    """
    if raw_household is None:
        return ""

    if isinstance(raw_household, list):
        candidates = [str(item).strip() for item in raw_household if str(item).strip()]
        if not candidates:
            return ""
        text = candidates[0]
    else:
        text = str(raw_household).strip()
        if not text:
            return ""

    text = re.sub(r'^(purposeful\s+household\s+task\s*:?\s*)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^(i\s+do|i\s+like|i\s+enjoy|my\s+household\s+task\s+is)\s+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+and\s+', ', ', text, flags=re.IGNORECASE)

    parts = [p.strip() for p in re.split(r'[,;]+', text) if p.strip()]
    if not parts:
        return ""

    primary = re.sub(r'^[^\w]+|[^\w]+$', '', parts[0]).strip()
    return primary.title() if primary else ""


def extract_primary_social_activity(raw_social):
    """Returns one cleaned social activity from questionnaire input."""
    if raw_social is None:
        return ""

    if isinstance(raw_social, list):
        candidates = [str(item).strip() for item in raw_social if str(item).strip()]
        if not candidates:
            return ""
        text = candidates[0]
    else:
        text = str(raw_social).strip()
        if not text:
            return ""

    text = re.sub(r'^(social\s+connection\s*:?\s*)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^(i\s+do|i\s+like|i\s+enjoy|my\s+social\s+activity\s+is)\s+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+and\s+', ', ', text, flags=re.IGNORECASE)

    parts = [p.strip() for p in re.split(r'[,;]+', text) if p.strip()]
    if not parts:
        return ""

    primary = re.sub(r'^[^\w]+|[^\w]+$', '', parts[0]).strip()
    return primary.title() if primary else ""


def get_hobby_specific_link(hobby_name):
    """Return a hobby-relevant external link for Tuesday's hobby session."""
    hobby = str(hobby_name or "").strip().lower()
    if not hobby:
        return "https://livingyourseniorlife.com/hobby-ideas-for-seniors/?utm_source=chatgpt.com"

    hobby_links = {
        "dance": "https://www.youtube.com/watch?v=ujREEgxEP7g",
        "dancing": "https://www.youtube.com/watch?v=ujREEgxEP7g",
        "chess": "https://lichess.org/",
        "gardening": "https://www.gardenersworld.com/how-to/grow-plants/",
        "reading": "https://www.gutenberg.org/",
        "painting": "https://www.youtube.com/watch?v=Q3YzE4YcL3o",
        "music": "https://www.youtube.com/watch?v=5qap5aO4i9A",
        "knitting": "https://www.youtube.com/watch?v=p_R1UDsNOMk",
        "cooking": "https://www.bbcgoodfood.com/recipes/category/healthy",
        "yoga": "https://www.youtube.com/watch?v=v7AYKMP6rOE",
        "walking": "https://www.alltrails.com/?utm_source=chatgpt.com"
    }

    for keyword, link in hobby_links.items():
        if keyword in hobby:
            return link

    # Fallback: still hobby-related even for uncommon hobbies.
    query = hobby.replace(" ", "+")
    return f"https://www.youtube.com/results?search_query={query}+tutorial"


def generate_routine(profile_data, feedback=None):
    # Extract list of individual hobbies
    raw_hobbies = profile_data.get("hobbies", "")
    hobbies = extract_hobbies_list(raw_hobbies)

    has_hobby_input = bool(str(raw_hobbies).strip()) and hobbies and hobbies[0].lower() != "your favorite hobby"
    hobby_tuesday = hobbies[0] if has_hobby_input else ""
    hobby_thursday = ""
    hobby_saturday = ""
    if has_hobby_input:
        hobby_thursday = hobbies[1] if len(hobbies) > 1 else hobbies[0]
        hobby_saturday = hobbies[2] if len(hobbies) > 2 else (hobbies[1] if len(hobbies) > 1 else hobbies[0])

    tuesday_hobby_title = f"Hobby Session: {hobby_tuesday}" if hobby_tuesday else "Hobby Session"
    tuesday_hobby_desc = (
        f"Focusing on {hobby_tuesday.lower()} triggers a psychological flow state, boosting natural dopamine."
        if hobby_tuesday
        else "Spending time on a hobby supports mood, focus, and emotional balance."
    )
    tuesday_hobby_link = get_hobby_specific_link(hobby_tuesday)

    hobby_fallback_link = "https://freedomsquarefl.com/blog/hobby-ideas-for-seniors/"
    thursday_hobby_title = f"Hobby Session: {hobby_thursday}" if hobby_thursday else "Hobby Session"
    thursday_hobby_desc = (
        f"Immersing in {hobby_thursday.lower()} offers deep self-expression and mental relaxation."
        if hobby_thursday
        else "Spending time on a hobby supports mood, focus, and emotional balance."
    )
    thursday_hobby_link = get_hobby_specific_link(hobby_thursday) if hobby_thursday else hobby_fallback_link

    saturday_hobby_title = f"Hobby Session: {hobby_saturday}" if hobby_saturday else "Hobby Session"
    saturday_hobby_desc = (
        f"Spending unhurried time on {hobby_saturday.lower()} satisfies creative expression."
        if hobby_saturday
        else "Spending time on a hobby supports mood, focus, and emotional balance."
    )
    saturday_hobby_link = get_hobby_specific_link(hobby_saturday) if hobby_saturday else hobby_fallback_link

    physical = profile_data.get("physical_activities", ["Outdoor Walking"])
    primary_move = physical[0] if physical else "Gentle Walking"

    social = profile_data.get("social_pref", [])
    primary_social = extract_primary_social_activity(social)
    wednesday_social_title = f"Social Connection: {primary_social}" if primary_social else "Social Connection"
    wednesday_social_link = "https://connect2affect.org/easy-conversation-starters/?utm_source=chatgpt.com"

    cognitive = profile_data.get("brain_activities", ["Word & Memory Puzzles"])
    primary_cog = cognitive[0] if cognitive else "Memory Exercise"

    household = profile_data.get("household_tasks", [])
    primary_task = extract_primary_household_task(household)

    # Adjust activity titles based on reflection feedback
    if feedback:
        disliked = feedback.get("disliked", "").strip()
        hard = feedback.get("hard", "").strip()
        if hard or disliked:
            primary_move = f"Easier & Gentle {primary_move}"

    return {
        "Monday": {
            "theme": "Mindfulness Monday",
            "color": "#3b5284",
            "bg_color": "rgba(255, 255, 255, 0.45)",
            "tasks": [
                {
                    "name": "Morning Grounding",
                    "desc": "Connecting with physical senses lowers baseline cortisol levels and restores balance.",
                    "link": "https://www.youtube.com/watch?v=inpok4MKVLM",
                    "completed": False
                },
                {
                    "name": f"{primary_move}",
                    "desc": "Spending time outdoors reduces stress while refreshing both the mind and body.",
                    "link": "https://www.alltrails.com/?utm_source=chatgpt.com",
                    "completed": False
                },
                {
                    "name": "Brain and Memory Exercise",
                    "desc": "Cognitive stimulation strengthens neural pathways, aiding memory retention.",
                    "link": "https://seniorbraingames.org/play/memory-games/memory-card-match",
                    "completed": False
                },
                {
                    "name": "Body Scan Relaxation",
                    "desc": "Progressive body relaxation reduces physical tension accumulated over the day.",
                    "link": "https://www.youtube.com/watch?v=8v8Gl4wDWkc",
                    "completed": False
                }
            ]
        },
        "Tuesday": {
            "theme": "Therapy Tuesday",
            "color": "#4a5568",
            "bg_color": "rgba(255, 255, 255, 0.45)",
            "tasks": [
                {
                    "name": "Thought Journaling",
                    "desc": "Expressing worry on paper allows you to process emotions logically and self-compassionately.",
                    "link": "https://psychology.com/tools/journal-prompts?utm_source=chatgpt.com#tool",
                    "completed": False
                },
                {
                    "name": tuesday_hobby_title,
                    "desc": tuesday_hobby_desc,
                    "link": tuesday_hobby_link,
                    "completed": False
                },
                {
                    "name": f"Finger knitting or Crafting: {primary_task}" if primary_task else "Finger Knitting or Crafting",
                    "desc": "Completing a manageable task restores a sense of order and personal achievement.",
                    "link": "https://www.youtube.com/watch?v=MsZsUBYU0qU",
                    "completed": False
                },
                {
                    "name": "Evening Self-Affirmation",
                    "desc": "Reaffirming your daily efforts fosters resilience and improves emotional self-worth.",
                    "link": "https://psychology.com/tools/positive-affirmations?utm_source=chatgpt.com",
                    "completed": False
                }
            ]
        },
        "Wednesday": {
            "theme": "Wellness Wednesday",
            "color": "#2e6f53",
            "bg_color": "rgba(255, 255, 255, 0.45)",
            "tasks": [
                {
                    "name": "At-Home Workout",
                    "desc": "Engaging in a home workout boosts physical fitness and mental well-being.",
                    "link": "https://www.youtube.com/watch?v=WPPPFqsECz0",
                    "completed": False
                },
                {
                    "name": "Podcast Break",
                    "desc": "Meaningful audio content stimulates the mind, encourages curiosity, and supports emotional well-being.",
                    "link": "https://open.spotify.com/genre/0JQ5DArNBzkmxXHCqFLx2J?utm_source=chatgpt.com",
                    "completed": False
                },
                {
                    "name": wednesday_social_title,
                    "desc": (
                        f"Reaching out through {primary_social.lower()} combats feelings of isolation."
                        if primary_social
                        else "Connecting with others supports mood, confidence, and emotional well-being."
                    ),
                    "link": wednesday_social_link,
                    "completed": False
                },
                {
                    "name": "Sleep Breathing Exercise",
                    "desc": "Guided sleep breathing exercises relax the nervous system and prepare the body for restful sleep.",
                    "link": "https://www.youtube.com/watch?v=nqOm1HZyh8Y",
                    "completed": False
                }
            ]
        },
        "Thursday": {
            "theme": "Thankful Thursday",
            "color": "#5a6b82",
            "bg_color": "rgba(255, 255, 255, 0.45)",
            "tasks": [
                {
                    "name": "Gratitude Reflection",
                    "desc": "Intentionally recognizing positive details rewires brain pathways toward optimism.",
                    "link": "https://ggia.berkeley.edu/practice/three-good-things?utm_source=chatgpt.com",
                    "completed": False
                },
                {
                    "name": f"Social Outreach: {primary_social}",
                    "desc": "Connecting with loved ones reinforces safety, belonging, and emotional warmth.",
                    "link": "https://www.psychologytoday.com/",
                    "completed": False
                },
                {
                    "name": thursday_hobby_title,
                    "desc": thursday_hobby_desc,
                    "link": thursday_hobby_link,
                    "completed": False
                },
                {
                    "name": "Guided Meditation",
                    "desc": "Directing compassionate thoughts toward yourself and others calms anxiety.",
                    "link": "https://www.youtube.com/watch?v=Lzvj_JVZkzY",
                    "completed": False
                }
            ]
        },
        "Friday": {
            "theme": "Feel-It Friday",
            "color": "#435d7d",
            "bg_color": "rgba(255, 255, 255, 0.45)",
            "tasks": [
                {
                    "name": "Box Breathing Stress Reset",
                    "desc": "Equalized 4-second box breathing regulates oxygen levels, interrupting anxiety loops.",
                    "link": "https://www.youtube.com/watch?v=tEmt1Znux58",
                    "completed": False
                },
                {
                    "name": "Emotional Check-In",
                    "desc": "Accepting feelings without self-criticism prevents mental suppression and burnout.",
                    "link": "https://feelingswheel.app/",
                    "completed": False
                },
                {
                    "name": "Music & Sound Therapy Session",
                    "desc": "Comforting auditory rhythms lower physical agitation and release soothing neurotransmitters.",
                    "link": "https://www.youtube.com/watch?v=unCya_-8ECs",
                    "completed": False
                },
                {
                    "name": "Intention Building",
                    "desc": "Setting intentions for restful leisure creates clear psychological balance.",
                    "link": "https://www.flowstateplatform.com/tools/woop-method?utm_source=chatgpt.com",
                    "completed": False
                }
            ]
        },
        "Saturday": {
            "theme": "Self-Care Saturday",
            "color": "#316070",
            "bg_color": "rgba(255, 255, 255, 0.45)",
            "tasks": [
                {
                    "name": saturday_hobby_title,
                    "desc": saturday_hobby_desc,
                    "link": saturday_hobby_link,
                    "completed": False
                },
                {
                    "name": "Learn Something New",
                    "desc": "Learning something new strengthens cognitive function and keeps the brain engaged.",
                    "link": "https://ed.ted.com/lessons?utm_source=chatgpt.com",
                    "completed": False
                },
                {
                    "name": "Gentle Stretch",
                    "desc": "Warmth relaxes stiff joints and improves blood circulation.",
                    "link": "https://www.youtube.com/watch?v=3cSmYMYOciI",
                    "completed": False
                },
                {
                    "name": "Rose, Bud, Thorn Reflection",
                    "desc": "Reflecting on the day's highlights and challenges promotes gratitude and emotional clarity.",
                    "link": "https://www.colorado.edu/researchinnovation/rose-bud-thorn",
                    "completed": False
                }
            ]
        },
        "Sunday": {
            "theme": "Slow-Down Sunday",
            "color": "#52527a",
            "bg_color": "rgba(255, 255, 255, 0.45)",
            "tasks": [
                {
                    "name": "Morning Slow Movement",
                    "desc": "Starting the day unhurried keeps morning stress hormones low.",
                    "link": "https://www.youtube.com/watch?v=JwqUw3rQI34",
                    "completed": False
                },
                {
                    "name": "Goal Builder",
                    "desc": "Structuring simple goals eliminates anticipatory anxiety for the upcoming week.",
                    "link": "https://smartgoalbuilder.com/?utm_source=chatgpt.com#builder",
                    "completed": False
                },
                {
                    "name": f"Brain Stimulation: {primary_cog}",
                    "desc": f"Engaging in {primary_cog.lower()} keeps cognitive focus active and rewarding.",
                    "link": "https://seniorbraingames.org/play/word-games/word-scramble",
                    "completed": False
                },
                {
                    "name": "Bedtime Sleep Prep",
                    "desc": "A dark, quiet, and comfortable environment fosters restorative sleep quality.",
                    "link": "https://www.youtube.com/watch?v=pdJ9BFsLK-M",
                    "completed": False
                }
            ]
        }
    }
@app.route('/')
def home():
    if state.get("current_step") == "Landing":
        return render_template('landing.html')
    return render_template('index.html')

@app.route('/api/state', methods=['GET'])
def get_state():
    return jsonify(state)

@app.route('/api/navigate', methods=['POST'])
def navigate():
    data = request.json or {}
    state["current_step"] = data.get("step", "Landing")
    return jsonify({"success": True, "state": state})

@app.route('/api/onboarding', methods=['POST'])
def submit_onboarding():
    data = request.json or {}
    
    state["user_profile"] = {
        "mood": data.get("mood", "Neutral"),
        "challenges": data.get("challenges", ""),
        "energy_level": data.get("energy_level", "Steady Energy"),
        "physical_activities": data.get("physical_activities", []),
        "social_pref": data.get("social_pref", []),
        "brain_activities": data.get("brain_activities", []),
        "hobbies": data.get("hobbies", ""),
        "household_tasks": data.get("household_tasks", [])
    }
    
    state["mood_history"].append({
        "Date": "Today",
        "Mood": data.get("mood", "Neutral")
    })
    
    state["weekly_routine"] = generate_routine(state["user_profile"])
    state["selected_day"] = "Monday"
    state["current_step"] = "Plan"
    return jsonify({"success": True, "state": state})

@app.route('/api/select_day', methods=['POST'])
def select_day():
    data = request.json or {}
    state["selected_day"] = data.get("day", "Monday")
    return jsonify({"success": True, "state": state})

@app.route('/api/toggle_task', methods=['POST'])
def toggle_task():
    data = request.json or {}
    day = data.get("day")
    task_idx = data.get("task_idx")
    completed = data.get("completed")

    if day in state["weekly_routine"] and 0 <= task_idx < len(state["weekly_routine"][day]["tasks"]):
        state["weekly_routine"][day]["tasks"][task_idx]["completed"] = completed

    return jsonify({"success": True, "state": state})


@app.route('/api/medications', methods=['POST'])
def add_medication():
    data = request.json or {}
    med_name = str(data.get("name", "")).strip()
    med_time = str(data.get("time", "")).strip()

    if not med_name or not med_time:
        return jsonify({"success": False, "error": "Medication name and time are required."}), 400

    state["meds"] = [normalize_medication(m) for m in state.get("meds", [])]
    state["meds"].append(
        {
            "id": f"med-{int(datetime.now().timestamp() * 1000)}",
            "name": med_name,
            "time": med_time,
            "taken": False
        }
    )
    return jsonify({"success": True, "state": state})


@app.route('/api/medications/toggle', methods=['POST'])
def toggle_medication():
    data = request.json or {}
    med_id = str(data.get("id", "")).strip()
    taken = bool(data.get("taken", False))

    state["meds"] = [normalize_medication(m) for m in state.get("meds", [])]

    for med in state["meds"]:
        if med["id"] == med_id:
            med["taken"] = taken
            break

    return jsonify({"success": True, "state": state})

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json or {}
    user_msg = str(data.get("message", "")).strip()

    if user_msg:
        state["messages"].append({"role": "user", "content": user_msg})

    if client:
        try:
            profile = state.get("user_profile", {})
            challenges = profile.get("challenges", "general stress and daily balance")
            mood = profile.get("mood", "Neutral")

            system_prompt = {
                "role": "system",
                "content": (
                    f"You are a warm, gentle, empathetic AI Neuro Coach for older adults. "
                    f"User's current mood: '{mood}'. Challenges: '{challenges}'. "
                    f"Keep your responses extremely concise, conversational, and friendly—no more than 2 to 3 sentences maximum. "
                    f"Ask one natural, warm follow-up question to keep the conversation flowing naturally. "
                    f"Do not use markdown, bullet points, or special characters so text-to-speech reads smoothly."
                )
            }

            messages_to_send = [system_prompt] + state["messages"]

            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages_to_send,
                temperature=0.7,
                max_tokens=120  # Reduced to prevent long-winded answers
            )
            ai_response = completion.choices[0].message.content
        except Exception as e:
            print(f"Error in chat completion: {e}")
            ai_response = build_fallback_chat_response(user_msg, state.get("user_profile", {}), state.get("messages", []))
    else:
        ai_response = build_fallback_chat_response(user_msg, state.get("user_profile", {}), state.get("messages", []))

    state["messages"].append({"role": "assistant", "content": ai_response})
    return jsonify({"success": True, "messages": state["messages"]})

@app.route('/api/journal', methods=['POST'])
def save_journal():
    data = request.json or {}
    entry = data.get("entry", "")
    if entry:
        state["journal_entries"].append(entry)
    return jsonify({"success": True, "summary": "AI Summary: You are doing a great job expressing your feelings. Keep it up!"})

@app.route('/api/reflection', methods=['POST'])
def submit_reflection():
    data = request.json or {}
    
    liked = data.get("liked", "").strip()
    hard = data.get("hard", "").strip()
    disliked = data.get("disliked", "").strip()

    feedback = {
        "liked": liked,
        "hard": hard,
        "disliked": disliked
    }
    state["user_profile"]["last_week_feedback"] = feedback

    # Dynamically update next week's plan based on reflection feedback
    if client:
        try:
            system_prompt = (
                "You are an empathetic AI wellness coach. Review the user's reflection on last week's routine "
                "and update their 7-day routine (Monday to Sunday) for next week to integrate their feedback.\n"
                f"- What they enjoyed most: '{liked}'\n"
                f"- What was hard to complete: '{hard}'\n"
                f"- What they want to replace or adjust: '{disliked}'\n\n"
                "CRITICAL INSTRUCTIONS:\n"
                "1. If the user explicitly stated they dislike an activity, REPLACE IT with a completely new enjoyable activity.\n"
                "2. If an activity was too hard, replace or modify it to be significantly easier and gentler.\n"
                "3. Keep and emphasize activities similar to what they enjoyed.\n"
                "4. Return ONLY a valid JSON object with the exact structure containing keys: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.\n"
                "5. Each day must have 'theme' (str), 'color' (str hex), 'bg_color' ('rgba(255, 255, 255, 0.45)'), and 'tasks' (list of 4 tasks).\n"
                "6. Each task must have 'name' (str), 'desc' (str), 'link' (str), and 'completed' (boolean False)."
            )

            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Current Routine: {json.dumps(state['weekly_routine'])}"}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            updated_routine = json.loads(completion.choices[0].message.content)
            if updated_routine and "Monday" in updated_routine:
                state["weekly_routine"] = updated_routine
            else:
                state["weekly_routine"] = generate_routine(state["user_profile"], feedback=feedback)
        except Exception as e:
            print(f"Error regenerating routine with Groq: {e}")
            state["weekly_routine"] = generate_routine(state["user_profile"], feedback=feedback)
    else:
        state["weekly_routine"] = generate_routine(state["user_profile"], feedback=feedback)

    state["selected_day"] = "Monday"
    state["current_step"] = "Plan"
    return jsonify({"success": True, "state": state})
def open_browser():
    webbrowser.open_new(f"http://127.0.0.1:{PORT}/")

@app.route('/images/<path:filename>')
def serve_image(filename):
    # 1. Check if file is in an 'images' subfolder
    if os.path.exists(os.path.join('images', filename)):
        return send_from_directory('images', filename)
    # 2. Otherwise serve directly from the main project directory
    return send_from_directory('.', filename)

if __name__ == '__main__':
    print(f"Starting DailyMind server on http://127.0.0.1:{PORT}")

    # Default to hot-reload locally unless explicitly disabled.
    debug_setting = os.environ.get("FLASK_DEBUG")
    if debug_setting is None:
        debug_mode = not bool(os.environ.get("RENDER"))
    else:
        debug_mode = debug_setting == "1"

    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=debug_mode,
        load_dotenv=False,
        use_reloader=debug_mode
    )