import json
import os
import re
import webbrowser
from threading import Timer
from flask import Flask, jsonify, render_template, request, send_from_directory
from groq import Groq

app = Flask(
    __name__,
    template_folder='.',
    static_folder='.'
)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

PORT = int(os.environ.get("PORT", 5001))

state = {
    "current_step": "Landing",
    "selected_day": "Monday",
    "user_profile": {},
    "weekly_routine": {},
    "messages": [],
    "mood_history": [],
    "journal_entries": [],
    "meds": [
        {"Medicine": "Vitamin D", "Time": "8 AM", "Taken": True},
        {"Medicine": "Blood Pressure", "Time": "2 PM", "Taken": False},
        {"Medicine": "Calcium", "Time": "8 PM", "Taken": False}
    ]
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


def generate_routine(profile_data, feedback=None):
    # Extract list of individual hobbies
    raw_hobbies = profile_data.get("hobbies", "")
    hobbies = extract_hobbies_list(raw_hobbies)

    hobby_tuesday = hobbies[0] if len(hobbies) > 0 else "your favorite hobby"
    hobby_thursday = hobbies[1] if len(hobbies) > 1 else hobbies[0]
    hobby_saturday = hobbies[2] if len(hobbies) > 2 else hobbies[0]

    physical = profile_data.get("physical_activities", ["Outdoor Walking"])
    primary_move = physical[0] if physical else "Gentle Walking"

    social = profile_data.get("social_pref", ["Calling Family"])
    primary_social = social[0] if social else "Call a loved one"

    cognitive = profile_data.get("brain_activities", ["Word & Memory Puzzles"])
    primary_cog = cognitive[0] if cognitive else "Memory Exercise"

    household = profile_data.get("household_tasks", ["Watering Plants"])
    primary_task = household[0] if household else "Light Household Task"

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
                    "name": "Morning Grounding & Sensory Check-In",
                    "desc": "Connecting with physical senses lowers baseline cortisol levels and restores balance.",
                    "link": "https://www.youtube.com/watch?v=inpok4MKVLM",
                    "completed": False
                },
                {
                    "name": f"Physical Focus: {primary_move}",
                    "desc": f"Engaging in {primary_move.lower()} stimulates blood circulation to the brain, enhancing mood.",
                    "link": "https://www.healthline.com/nutrition/7-health-benefits-of-water",
                    "completed": False
                },
                {
                    "name": f"Brain & Memory Exercise: {primary_cog}",
                    "desc": "Cognitive stimulation strengthens neural pathways, aiding memory retention.",
                    "link": "https://www.medicalnewstoday.com/articles/324417",
                    "completed": False
                },
                {
                    "name": "Evening Body Scan Relaxation",
                    "desc": "Progressive body relaxation reduces physical tension accumulated over the day.",
                    "link": "https://www.mindful.org/a-body-scan-meditation-to-help-you-sleep/",
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
                    "name": "Morning Thought Reframing & Journaling",
                    "desc": "Expressing worry on paper allows you to process emotions logically and self-compassionately.",
                    "link": "https://www.psychologytoday.com/us/blog/shyness-is-not-loneliness/202105/how-journaling-eases-anxiety",
                    "completed": False
                },
                {
                    "name": f"Purpose & Flow Session: {hobby_tuesday}",
                    "desc": f"Focusing on {hobby_tuesday.lower()} triggers a psychological flow state, boosting natural dopamine.",
                    "link": "https://www.healthyplace.com/blogs/buildingselfesteem/2015/10/the-mental-health-benefits-of-having-a-hobby",
                    "completed": False
                },
                {
                    "name": f"Purposeful Household Task: {primary_task}",
                    "desc": "Completing a manageable task restores a sense of order and personal achievement.",
                    "link": "https://www.healthline.com/health/cognitive-distortions",
                    "completed": False
                },
                {
                    "name": "Evening Compassionate Self-Affirmation",
                    "desc": "Reaffirming your daily efforts fosters resilience and improves emotional self-worth.",
                    "link": "https://www.mindful.org/",
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
                    "name": "15-Minute Outdoor Light Refresh Walk",
                    "desc": "Natural light exposure boosts serotonin production, regulating biological rhythms.",
                    "link": "https://www.youtube.com/watch?v=WPPPFqsECz0",
                    "completed": False
                },
                {
                    "name": "Medication & Hydration Consistency Check",
                    "desc": "Routine health adherence stabilizes baseline physiological safety and overall energy.",
                    "link": "https://www.healthline.com/",
                    "completed": False
                },
                {
                    "name": f"Social Connection: {primary_social}",
                    "desc": f"Reaching out through {primary_social.lower()} combats feelings of isolation.",
                    "link": "https://www.psychologytoday.com/us/blog/the-social-self/202108/why-connecting-others-is-good-our-health",
                    "completed": False
                },
                {
                    "name": "Evening Herbal Tea & Gentle Wind-Down",
                    "desc": "Warm, caffeine-free herbal tea relaxes gastrointestinal muscles and calms the nervous system.",
                    "link": "https://www.sleepfoundation.org/nutrition/tea-for-sleep",
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
                    "name": "'Three Good Things' Gratitude Reflection",
                    "desc": "Intentionally recognizing positive details rewires brain pathways toward optimism.",
                    "link": "https://www.gratitude.plus/",
                    "completed": False
                },
                {
                    "name": f"Social Outreach: {primary_social}",
                    "desc": "Connecting with loved ones reinforces safety, belonging, and emotional warmth.",
                    "link": "https://www.psychologytoday.com/",
                    "completed": False
                },
                {
                    "name": f"Creative Hobby Deep-Dive: {hobby_thursday}",
                    "desc": f"Immersing in {hobby_thursday.lower()} offers deep self-expression and mental relaxation.",
                    "link": "https://www.healthyplace.com/",
                    "completed": False
                },
                {
                    "name": "Evening Loving-Kindness Meditation",
                    "desc": "Directing compassionate thoughts toward yourself and others calms anxiety.",
                    "link": "https://www.mindful.org/a-loving-kindness-meditation-to-boost-compassion/",
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
                    "name": "Non-Judgmental Emotional Check-In",
                    "desc": "Accepting feelings without self-criticism prevents mental suppression and burnout.",
                    "link": "https://www.mindful.org/",
                    "completed": False
                },
                {
                    "name": "Music & Sound Therapy Session",
                    "desc": "Comforting auditory rhythms lower physical agitation and release soothing neurotransmitters.",
                    "link": "https://www.youtube.com/watch?v=WPPPFqsECz0",
                    "completed": False
                },
                {
                    "name": "Weekend Boundaries & Rest Preparation",
                    "desc": "Setting intentions for restful leisure creates clear psychological balance.",
                    "link": "https://www.healthline.com/",
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
                    "name": f"Extended Hobby Session: {hobby_saturday}",
                    "desc": f"Spending unhurried time on {hobby_saturday.lower()} satisfies creative expression.",
                    "link": "https://www.healthyplace.com/",
                    "completed": False
                },
                {
                    "name": "Digital Detox & Screen-Free Rest Hour",
                    "desc": "Stepping away from screens calms overstimulated neural pathways.",
                    "link": "https://www.healthline.com/",
                    "completed": False
                },
                {
                    "name": "Warm Relaxation & Gentle Stretch",
                    "desc": "Warmth relaxes stiff joints and improves blood circulation.",
                    "link": "https://www.healthline.com/",
                    "completed": False
                },
                {
                    "name": "Joyful Entertainment & Laughter",
                    "desc": "Laughter releases natural endorphins, instantly lifting mood and decreasing tension.",
                    "link": "https://www.helpguide.org/articles/mental-health/laughter-is-the-best-medicine.htm",
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
                    "name": "Gentle Morning & Slow Movement",
                    "desc": "Starting the day unhurried keeps morning stress hormones low.",
                    "link": "https://www.youtube.com/watch?v=inpok4MKVLM",
                    "completed": False
                },
                {
                    "name": "Low-Pressure Planning for Next Week",
                    "desc": "Structuring simple goals eliminates anticipatory anxiety for the upcoming week.",
                    "link": "https://www.mindful.org/",
                    "completed": False
                },
                {
                    "name": f"Brain Stimulation: {primary_cog}",
                    "desc": f"Engaging in {primary_cog.lower()} keeps cognitive focus active and rewarding.",
                    "link": "https://www.healthline.com/",
                    "completed": False
                },
                {
                    "name": "Bedtime Sleep Environment Prep",
                    "desc": "A dark, quiet, and comfortable environment fosters restorative sleep quality.",
                    "link": "https://www.youtube.com/watch?v=aEqlQv71mI0",
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

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json or {}
    user_msg = data.get("message", "")

    if user_msg:
        state["messages"].append({"role": "user", "content": user_msg})

    if client:
        try:
            profile = state.get("user_profile", {})
            challenges = profile.get("challenges", "general stress and daily balance")
            hobbies = profile.get("hobbies", "their favorite hobbies")
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
            ai_response = f"I am here with you and listening. How are you feeling right now? (API Notice: {str(e)})"
    else:
        profile = state.get("user_profile", {})
        challenges = profile.get("challenges", "")
        if challenges:
            ai_response = f"I hear you and understand. How are you holding up with {challenges} today?"
        else:
            ai_response = "I am listening and here with you. How can I support you today?"

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
    if not os.environ.get("RENDER") and os.environ.get("DISABLE_BROWSER_OPEN") != "1":
        Timer(1.2, open_browser).start()
    app.run(host='0.0.0.0', port=PORT, debug=os.environ.get("FLASK_DEBUG") == "1")