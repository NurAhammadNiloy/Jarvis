import openai
from config.api_keys import OPENAI_API_KEY
from config.settings import NETWORK_TIMEOUT_SECONDS
from core.service_errors import ServiceError

openai.api_key = OPENAI_API_KEY

# Conversation history for context
_conversation_history = []
MAX_HISTORY = 10  # Keep last 10 exchanges for context


def resolve_dialogue(context):
    """One bounded model call for conversation and request repair; no tools."""
    import json
    response = openai.ChatCompletion.create(
        model='gpt-4o', temperature=0, max_tokens=250, request_timeout=8,
        messages=[{'role': 'system', 'content': (
            'You are Jarvis in a spoken conversation. Reply naturally in one short sentence, '
            'without roleplay filler. Use the supplied recent turns to understand follow-ups, '
            'corrections, spelling and topic changes. Recognition text is fallible: alternatives '
            'are possibilities, not user statements. Preserve agreed details. Ask ONE targeted '
            'question about the uncertain or missing detail, not for repetition of the full request. '
            'For example, if alternatives differ only on a person, ask who to call and retain the time. '
            'Do not invent names, times, targets or user agreement. A correction is not an action '
            'authorization. You cannot execute anything. Never claim an action succeeded. '
            'Return ONLY JSON with exactly reply (string) and query (string or null). '
            'For conversation or a missing/uncertain detail use query null. For a complete requested '
            'action, query is a standalone plain-text command for confirmation. Supported actions '
            'are reminders (create, delete, snooze), alarms, timers, weather, date/time, YouTube and opening Google.  '
            'Do not propose unsupported actions. For a reminder preserve task, time and recurrence. '
            'If the user changes topic, answer that topic; do not force the pending request.'
        )}, {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}])
    return json.loads(response['choices'][0]['message']['content'])

def add_to_history(role: str, content: str):
    """Add a message to conversation history."""
    _conversation_history.append({"role": role, "content": content})
    # Trim if too long
    while len(_conversation_history) > MAX_HISTORY * 2:
        _conversation_history.pop(0)

def clear_history():
    """Clear conversation history."""
    _conversation_history.clear()

def get_chatgpt_response(query: str) -> str:
    """
    Get a response from ChatGPT with conversation context.
    Maintains history for follow-up questions.
    """
    try:
        # Build messages with system prompt and history
        messages = [
            {
                "role": "system", 
                "content": (
                    "You are Jarvis, an AI assistant like from Iron Man. "
                    "Keep responses short and conversational (2-3 sentences max). "
                    "Be helpful, witty, and address the user as 'sir' occasionally. "
                    "Remember the conversation context to answer follow-up questions."
                )
            }
        ]
        
        # Add conversation history for context
        messages.extend(_conversation_history)
        
        # Add current query
        messages.append({"role": "user", "content": query})
        
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.3,
            max_tokens=150,  # Increased slightly for better answers
            request_timeout=NETWORK_TIMEOUT_SECONDS
        )
        
        assistant_response = response['choices'][0]['message']['content']
        
        # Store in history for future context
        add_to_history("user", query)
        add_to_history("assistant", assistant_response)
        
        return assistant_response
        
    except openai.error.Timeout as e:
        print(f"Error with ChatGPT: {e}")
        raise ServiceError("ChatGPT took too long to respond. Please try again.")
    except Exception as e:
        print(f"Error with ChatGPT: {e}")
        raise ServiceError("I'm sorry, I couldn't get a response from ChatGPT.")
