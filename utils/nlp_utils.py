"""
=============================================================================
Advanced NLP Utilities for Jarvis AI Assistant
=============================================================================
Comprehensive natural language understanding with maximum capabilities.

Features:
- Entity extraction (time, location, person, organization, etc.)
- Intent classification
- Sentiment analysis
- Emotion detection
- Urgency detection
- Query type classification
- Text normalization & tokenization
- Keyword extraction
- Pronoun resolution
- Follow-up detection
- Semantic similarity
- Text summarization
=============================================================================
"""

import spacy
import re
import dateparser
from datetime import datetime, timedelta
from textblob import TextBlob
from collections import Counter
import json

# Load the transformer-based model for best accuracy
nlp = spacy.load("en_core_web_trf")


# =============================================================================
# CONFIGURATION & PATTERNS
# =============================================================================

# Time extraction patterns (ordered by specificity)
TIME_PATTERNS = [
    # Specific times with AM/PM
    r'(?:at\s+)?(\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.))',
    r'(?:at\s+)?(\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.))',
    # "at X" where X is a number (interpret as time, not month)
    r'at\s+(\d{1,2})(?:\s|$)',
    # 24-hour format
    r'(?:at\s+)?(\d{1,2}:\d{2})',
    # Relative times
    r'(in\s+\d+\s*(?:minute|min|minutes|mins|hour|hours|hr|hrs|day|days|week|weeks|second|seconds|sec|secs)s?)',
    r'(after\s+\d+\s*(?:minute|min|minutes|mins|hour|hours|hr|hrs|day|days)s?)',
    # Named times
    r'(tonight|tomorrow|today|yesterday|this\s+(?:morning|afternoon|evening|night))',
    r'(tomorrow\s+(?:morning|afternoon|evening|night))',
    r'(next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year))',
    r'(last\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year))',
    # Date patterns
    r'(?:on\s+)?(\w+\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)',
    r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?\w+)',
    r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)',
    r'(\d{4}-\d{2}-\d{2})',
]

# Patterns to remove from task extraction
REMOVE_PATTERNS = [
    r'^(?:please\s+)?remind\s+me\s+(?:to\s+)?',
    r'^(?:please\s+)?set\s+(?:a\s+)?reminder\s+(?:to\s+|for\s+)?',
    r'^(?:please\s+)?create\s+(?:a\s+)?reminder\s+(?:to\s+|for\s+)?',
    r'^(?:please\s+)?add\s+(?:a\s+)?reminder\s+(?:to\s+|for\s+)?',
    r'^(?:please\s+)?schedule\s+(?:a\s+)?(?:reminder\s+)?(?:to\s+|for\s+)?',
    r'^(?:i\s+)?(?:need|want)\s+(?:a\s+)?reminder\s+(?:to\s+|for\s+)?',
    r'^(?:can|could|would)\s+you\s+(?:please\s+)?remind\s+me\s+(?:to\s+)?',
    r'^(?:don\'t\s+let\s+me\s+forget\s+to\s+)',
    r'\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?',
    r'\s+at\s+\d{1,2}(?::\d{2})?',
    r'\s+in\s+\d+\s*(?:minute|min|minutes|mins|hour|hours|hr|hrs|day|days)s?',
    r'\s+(?:on\s+)?tomorrow(?:\s+(?:morning|afternoon|evening|night))?',
    r'\s+(?:on\s+)?today',
    r'\s+(?:on\s+)?tonight',
    r'\s+(?:on\s+)?this\s+(?:morning|afternoon|evening|night)',
    r'\s+(?:on\s+)?next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month)',
    r'\s+every\s*(?:day|week|month|hour)',
]

# Intent keywords mapping
INTENT_KEYWORDS = {
    'reminder': ['remind', 'reminder', 'alert', 'notify', 'don\'t forget', 'remember'],
    'weather': ['weather', 'temperature', 'forecast', 'rain', 'sunny', 'cloudy', 'snow', 'humid', 'wind', 'storm', 'climate'],
    'time': ['time', 'clock', 'hour', 'what time'],
    'date': ['date', 'day', 'today', 'what day', 'calendar'],
    'music': ['play', 'music', 'song', 'playlist', 'spotify', 'youtube music'],
    'youtube': ['youtube', 'video', 'watch', 'stream'],
    'search': ['search', 'google', 'look up', 'find', 'browse', 'lookup'],
    'news': ['news', 'headlines', 'breaking', 'latest', 'current events'],
    'email': ['email', 'mail', 'inbox', 'send email', 'compose'],
    'calendar': ['calendar', 'meeting', 'appointment', 'schedule', 'event'],
    'alarm': ['alarm', 'wake', 'wake up', 'timer'],
    'note': ['note', 'write down', 'jot down', 'memo', 'take note'],
    'calculate': ['calculate', 'math', 'compute', 'what is', 'how much', 'plus', 'minus', 'multiply', 'divide', 'percent'],
    'translate': ['translate', 'translation', 'say in', 'how do you say'],
    'definition': ['define', 'definition', 'meaning', 'what does', 'what is a', 'dictionary'],
    'joke': ['joke', 'funny', 'laugh', 'humor', 'tell me something funny'],
    'greeting': ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening', 'howdy', 'greetings'],
    'goodbye': ['bye', 'goodbye', 'see you', 'farewell', 'good night', 'talk later', 'later'],
    'thanks': ['thank', 'thanks', 'appreciate', 'grateful', 'thank you'],
    'help': ['help', 'assist', 'support', 'how do i', 'how can i', 'what can you do'],
    'status': ['status', 'how are you', 'are you there', 'you okay', 'are you awake'],
    'stop': ['stop', 'cancel', 'abort', 'nevermind', 'never mind', 'forget it', 'quit'],
    'repeat': ['repeat', 'say again', 'what did you say', 'pardon', 'come again'],
    'volume': ['volume', 'louder', 'quieter', 'mute', 'unmute', 'sound'],
    'lights': ['light', 'lights', 'lamp', 'brightness', 'dim', 'bright', 'turn on light', 'turn off light'],
    'temperature_control': ['thermostat', 'ac', 'air conditioning', 'heating', 'heater', 'cool', 'warm'],
    'navigation': ['navigate', 'directions', 'route', 'how to get', 'map', 'distance', 'gps'],
    'call': ['call', 'phone', 'dial', 'ring', 'contact'],
    'message': ['message', 'text', 'sms', 'send message', 'whatsapp'],
    'photo': ['photo', 'picture', 'camera', 'selfie', 'screenshot'],
    'settings': ['settings', 'preferences', 'configure', 'setup', 'options'],
    'system': ['system', 'battery', 'memory', 'storage', 'cpu', 'performance'],
    'app': ['open', 'launch', 'start', 'run', 'application', 'app'],
}

# Sentiment intensity thresholds
SENTIMENT_THRESHOLDS = {
    'very_negative': -0.6,
    'negative': -0.2,
    'neutral': 0.2,
    'positive': 0.6,
    'very_positive': 1.0
}

# Question words for classification
QUESTION_WORDS = [
    'what', 'when', 'where', 'who', 'whom', 'whose', 'why', 'how', 'which', 
    'is', 'are', 'can', 'could', 'would', 'should', 'do', 'does', 'did', 
    'will', 'have', 'has', 'had', 'may', 'might', 'shall'
]

# Command verbs
COMMAND_VERBS = [
    'play', 'open', 'start', 'stop', 'turn', 'set', 'show', 'tell', 'find', 
    'search', 'get', 'give', 'make', 'create', 'add', 'remove', 'delete', 
    'change', 'update', 'send', 'call', 'read', 'write', 'close', 'pause', 
    'resume', 'skip', 'next', 'previous', 'mute', 'unmute', 'increase', 
    'decrease', 'enable', 'disable', 'switch', 'toggle', 'check', 'list',
    'remind', 'schedule', 'cancel', 'clear', 'reset', 'restart', 'shutdown',
    'lock', 'unlock', 'connect', 'disconnect', 'download', 'upload', 'save'
]

# Urgency indicators
URGENCY_WORDS = {
    'high': ['urgent', 'asap', 'immediately', 'right now', 'emergency', 'critical', 
             'important', 'priority', 'hurry', 'quick', 'fast', 'now', 'instant'],
    'medium': ['soon', 'today', 'this afternoon', 'this evening', 'before', 'by', 
               'within', 'shortly'],
    'low': ['whenever', 'sometime', 'eventually', 'no rush', 'when you can', 
            'later', 'anytime', 'no hurry']
}

# Negation words
NEGATION_WORDS = [
    'not', 'no', 'never', 'neither', 'nobody', 'nothing', 'nowhere', 'none', 
    'don\'t', 'doesn\'t', 'didn\'t', 'won\'t', 'wouldn\'t', 'can\'t', 'couldn\'t', 
    'shouldn\'t', 'isn\'t', 'aren\'t', 'wasn\'t', 'weren\'t', 'haven\'t', 
    'hasn\'t', 'hadn\'t', 'without', 'lack'
]

# Confirmation words
CONFIRMATION_WORDS = [
    'yes', 'yeah', 'yep', 'yup', 'sure', 'okay', 'ok', 'alright', 'correct', 
    'right', 'definitely', 'absolutely', 'certainly', 'indeed', 'affirmative', 
    'confirm', 'confirmed', 'agree', 'accepted', 'exactly', 'perfect', 'great',
    'fine', 'proceed', 'go ahead', 'do it', 'that\'s right', 'of course'
]

# Denial words  
DENIAL_WORDS = [
    'no', 'nope', 'nah', 'negative', 'wrong', 'incorrect', 'deny', 'refuse', 
    'reject', 'cancel', 'stop', 'abort', 'nevermind', 'never mind', 'forget it',
    'not really', 'not now', 'not yet', 'don\'t', 'wait'
]

# Politeness indicators
POLITE_WORDS = [
    'please', 'kindly', 'could you', 'would you', 'may i', 'excuse me',
    'if you don\'t mind', 'when you have time', 'i would appreciate'
]

# Emotion patterns
EMOTION_PATTERNS = {
    'happy': ['happy', 'glad', 'joy', 'joyful', 'excited', 'wonderful', 'great', 
              'amazing', 'love', 'loving', 'yay', 'awesome', 'fantastic', 'excellent',
              'pleased', 'delighted', 'thrilled', 'ecstatic', 'cheerful', '😊', '😄', '🎉', '❤️'],
    'sad': ['sad', 'unhappy', 'depressed', 'upset', 'disappointed', 'sorry', 
            'unfortunately', 'miss', 'missing', 'lonely', 'heartbroken', 'grief',
            'melancholy', 'gloomy', 'down', '😢', '😔', '😞', '💔'],
    'angry': ['angry', 'mad', 'furious', 'annoyed', 'frustrated', 'hate', 'terrible',
              'irritated', 'outraged', 'enraged', 'livid', 'pissed', 'infuriated',
              '😠', '😡', '🤬'],
    'fearful': ['scared', 'afraid', 'worried', 'anxious', 'nervous', 'terrified', 
                'panic', 'fear', 'frightened', 'alarmed', 'concerned', 'uneasy',
                '😰', '😨', '😱'],
    'surprised': ['surprised', 'shocked', 'amazed', 'wow', 'unbelievable', 'incredible',
                  'astonished', 'stunned', 'unexpected', 'startled', '😮', '😲', '🤯'],
    'confused': ['confused', 'puzzled', 'unclear', 'don\'t understand', 'what do you mean',
                 'lost', 'perplexed', 'bewildered', 'baffled', '🤔', '😕', '❓'],
    'grateful': ['thank', 'thanks', 'grateful', 'appreciate', 'thankful', 'gratitude',
                 '🙏', '💐'],
    'apologetic': ['sorry', 'apologize', 'apologies', 'my bad', 'excuse me', 'pardon',
                   'forgive me', 'my fault', 'i apologize'],
    'curious': ['wondering', 'curious', 'interested', 'want to know', 'tell me about',
                'what about', 'how about', '🤔'],
    'bored': ['bored', 'boring', 'dull', 'uninteresting', 'tedious', 'monotonous', '😴'],
    'tired': ['tired', 'exhausted', 'sleepy', 'fatigued', 'worn out', 'drained', '😫', '🥱'],
}

# Topic categories
TOPIC_CATEGORIES = {
    'technology': ['computer', 'phone', 'software', 'app', 'internet', 'code', 'programming',
                   'ai', 'artificial intelligence', 'robot', 'device', 'gadget'],
    'health': ['health', 'medical', 'doctor', 'medicine', 'exercise', 'diet', 'wellness',
               'hospital', 'symptom', 'treatment', 'therapy'],
    'finance': ['money', 'bank', 'finance', 'invest', 'stock', 'crypto', 'budget', 'pay',
                'cost', 'price', 'expense', 'income', 'salary'],
    'entertainment': ['movie', 'music', 'game', 'show', 'series', 'book', 'read', 'watch',
                      'listen', 'play', 'fun', 'enjoy'],
    'travel': ['travel', 'trip', 'flight', 'hotel', 'vacation', 'destination', 'visit',
               'journey', 'tour', 'explore'],
    'food': ['food', 'eat', 'cook', 'recipe', 'restaurant', 'meal', 'breakfast', 'lunch',
             'dinner', 'hungry', 'drink'],
    'work': ['work', 'job', 'office', 'meeting', 'project', 'deadline', 'task', 'business',
             'career', 'professional'],
    'education': ['learn', 'study', 'school', 'university', 'course', 'class', 'education',
                  'teach', 'student', 'exam', 'homework'],
    'social': ['friend', 'family', 'relationship', 'party', 'social', 'people', 'meet',
               'talk', 'conversation', 'connect'],
    'weather': ['weather', 'rain', 'sun', 'snow', 'temperature', 'climate', 'forecast',
                'cold', 'hot', 'warm', 'cool'],
}


# =============================================================================
# CORE EXTRACTION FUNCTIONS
# =============================================================================

def extract_time_from_text(text):
    """
    Extract time/date information from text using regex and dateparser.
    Prefers the nearest future time when AM/PM is not specified.
    
    Args:
        text (str): The input text to parse.
        
    Returns:
        tuple: (extracted_time_str, parsed_datetime or None)
    """
    text_lower = text.lower().strip()
    now = datetime.now()
    
    # Try regex patterns first
    for pattern in TIME_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            time_str = match.group(1).strip()
            
            # Special handling for times without AM/PM (e.g., "8:23" or "8")
            # Find the nearest future occurrence
            time_match = re.match(r'^(\d{1,2})(?::(\d{2}))?$', time_str)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                
                if 1 <= hour <= 12:
                    # Try both AM and PM, pick the nearest future time
                    am_hour = hour if hour != 12 else 0
                    pm_hour = hour + 12 if hour != 12 else 12
                    
                    am_time = now.replace(hour=am_hour, minute=minute, second=0, microsecond=0)
                    pm_time = now.replace(hour=pm_hour, minute=minute, second=0, microsecond=0)
                    
                    # If AM time is in the past, try tomorrow AM
                    if am_time <= now:
                        am_time += timedelta(days=1)
                    
                    # If PM time is in the past, try tomorrow PM
                    if pm_time <= now:
                        pm_time += timedelta(days=1)
                    
                    # Pick the nearest future time
                    if am_time < pm_time:
                        parsed = am_time
                        suffix = "AM"
                    else:
                        parsed = pm_time
                        suffix = "PM"
                    
                    formatted_time = f"{hour}:{minute:02d} {suffix}"
                    return formatted_time, parsed
                
                elif 0 <= hour <= 23:
                    # 24-hour format
                    parsed = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if parsed <= now:
                        parsed += timedelta(days=1)
                    return time_str, parsed
            
            # Check if AM/PM is already specified - use dateparser
            if re.search(r'(am|pm|a\.m\.|p\.m\.)', time_str, re.IGNORECASE):
                parsed = dateparser.parse(
                    time_str,
                    settings={
                        'PREFER_DATES_FROM': 'future',
                        'PREFER_DAY_OF_MONTH': 'first',
                        'RETURN_AS_TIMEZONE_AWARE': False,
                        'RELATIVE_BASE': now
                    }
                )
                if parsed:
                    if parsed <= now:
                        parsed += timedelta(days=1)
                    return time_str, parsed
            
            # Try to parse with dateparser for other formats
            parsed = dateparser.parse(
                time_str,
                settings={
                    'PREFER_DATES_FROM': 'future',
                    'PREFER_DAY_OF_MONTH': 'first',
                    'RETURN_AS_TIMEZONE_AWARE': False,
                    'RELATIVE_BASE': now,
                    'PARSERS': ['relative-time', 'absolute-time', 'timestamp']
                }
            )
            if parsed:
                # Ensure it's in the future
                if parsed <= now:
                    parsed += timedelta(days=1)
                return time_str, parsed
            return time_str, None
    
    # Fallback: Try dateparser on segments of the text
    words = text_lower.split()
    for i in range(len(words)):
        for j in range(i + 1, min(i + 6, len(words) + 1)):
            segment = ' '.join(words[i:j])
            parsed = dateparser.parse(
                segment,
                settings={
                    'PREFER_DATES_FROM': 'future',
                    'RETURN_AS_TIMEZONE_AWARE': False
                }
            )
            if parsed and parsed > now:
                return segment, parsed
    
    return None, None


def extract_task_from_text(text, time_str=None):
    """
    Extract the task/action from the text by removing command and time phrases.
    
    Args:
        text (str): The input text.
        time_str (str): The extracted time string to remove.
        
    Returns:
        str: The cleaned task description.
    """
    task = text.strip()
    
    # Remove command prefixes (case insensitive)
    for pattern in REMOVE_PATTERNS:
        task = re.sub(pattern, ' ', task, flags=re.IGNORECASE)
    
    # Remove the specific time string if found
    if time_str:
        task = re.sub(re.escape(time_str), '', task, flags=re.IGNORECASE)
    
    # Clean up extra whitespace
    task = re.sub(r'\s+', ' ', task).strip()
    
    # Remove leading/trailing prepositions and articles
    task = re.sub(r'^(?:to|for|about|that|the|a|an)\s+', '', task, flags=re.IGNORECASE)
    task = re.sub(r'\s+(?:at|on|in|for)$', '', task, flags=re.IGNORECASE)
    
    return task.strip()


def extract_entities(doc):
    """
    Extract comprehensive entities from the user query using spaCy + regex + dateparser.
    
    Args:
        doc (spacy.tokens.Doc or str): The parsed doc object or raw text.
        
    Returns:
        dict: A dictionary containing all extracted entities.
    """
    # Handle both string and doc input
    if isinstance(doc, str):
        text = doc
        spacy_doc = nlp(text)
    else:
        text = doc.text
        spacy_doc = doc
    
    entities = {
        # Core entities
        'TASK': '',
        'TIME': None,
        'TIME_PARSED': None,
        'RECURRING': False,
        'INTERVAL': None,
        
        # Named entities
        'PERSON': [],
        'LOCATION': [],
        'ORGANIZATION': [],
        'PRODUCT': [],
        'EVENT': [],
        'MONEY': None,
        'QUANTITY': [],
        'CARDINAL': [],
        'ORDINAL': [],
        'PERCENT': None,
        'LANGUAGE': None,
        
        # Additional context
        'SUBJECT': None,
        'ACTION': None,
        'OBJECT': None,
        'KEYWORDS': [],
        'URLS': [],
        'EMAILS': [],
        'PHONE_NUMBERS': [],
        
        # Semantic flags
        'HAS_QUESTION': False,
        'HAS_NEGATION': False,
        'IS_CONFIRMATION': False,
        'IS_DENIAL': False,
        'IS_POLITE': False,
    }
    
    # Check for recurring patterns
    recurring_patterns = {
        'daily': r'\b(?:every\s*day|daily|each\s*day)\b',
        'weekly': r'\b(?:every\s*week|weekly|each\s*week)\b',
        'hourly': r'\b(?:every\s*hour|hourly|each\s*hour)\b',
        'monthly': r'\b(?:every\s*month|monthly|each\s*month)\b',
        'yearly': r'\b(?:every\s*year|yearly|annually|each\s*year)\b',
        'weekdays': r'\b(?:every\s*weekday|weekdays|monday\s*(?:through|to)\s*friday)\b',
        'weekends': r'\b(?:every\s*weekend|weekends)\b',
    }
    
    for interval, pattern in recurring_patterns.items():
        if re.search(pattern, text.lower()):
            entities['RECURRING'] = True
            entities['INTERVAL'] = interval
            break
    
    # Extract time using our enhanced function
    time_str, parsed_time = extract_time_from_text(text)
    if time_str:
        entities['TIME'] = time_str
        entities['TIME_PARSED'] = parsed_time
    
    # Extract task
    entities['TASK'] = extract_task_from_text(text, time_str)
    
    # Extract URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
    entities['URLS'] = re.findall(url_pattern, text)
    
    # Extract emails
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    entities['EMAILS'] = re.findall(email_pattern, text)
    
    # Extract phone numbers
    phone_pattern = r'(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}'
    entities['PHONE_NUMBERS'] = re.findall(phone_pattern, text)
    
    # Check for question
    words = text.lower().split()
    entities['HAS_QUESTION'] = '?' in text or (words[0] in QUESTION_WORDS if words else False)
    
    # Check for negation
    entities['HAS_NEGATION'] = any(neg in text.lower() for neg in NEGATION_WORDS)
    
    # Check for confirmation/denial
    first_word = words[0] if words else ''
    entities['IS_CONFIRMATION'] = first_word in CONFIRMATION_WORDS or any(word in text.lower() for word in CONFIRMATION_WORDS[:5])
    entities['IS_DENIAL'] = first_word in DENIAL_WORDS or any(word in text.lower() for word in DENIAL_WORDS[:5])
    
    # Check for politeness
    entities['IS_POLITE'] = any(polite in text.lower() for polite in POLITE_WORDS)
    
    # Extract spaCy entities
    for ent in spacy_doc.ents:
        label = ent.label_
        
        if label in ['TIME', 'DATE'] and not entities['TIME']:
            entities['TIME'] = ent.text
            parsed = dateparser.parse(ent.text, settings={'PREFER_DATES_FROM': 'future'})
            if parsed:
                entities['TIME_PARSED'] = parsed
                
        elif label == 'PERSON':
            entities['PERSON'].append(ent.text)
            
        elif label in ['GPE', 'LOC', 'FAC']:
            entities['LOCATION'].append(ent.text)
            
        elif label == 'ORG':
            entities['ORGANIZATION'].append(ent.text)
            
        elif label == 'PRODUCT':
            entities['PRODUCT'].append(ent.text)
            
        elif label == 'EVENT':
            entities['EVENT'].append(ent.text)
            
        elif label == 'MONEY':
            entities['MONEY'] = ent.text
            
        elif label == 'QUANTITY':
            entities['QUANTITY'].append(ent.text)
            
        elif label == 'CARDINAL':
            entities['CARDINAL'].append(ent.text)
            
        elif label == 'ORDINAL':
            entities['ORDINAL'].append(ent.text)
            
        elif label == 'PERCENT':
            entities['PERCENT'] = ent.text
            
        elif label == 'LANGUAGE':
            entities['LANGUAGE'] = ent.text
    
    # Extract subject, action, object using dependency parsing
    for token in spacy_doc:
        if token.dep_ == 'nsubj' and not entities['SUBJECT']:
            entities['SUBJECT'] = token.text
        elif token.dep_ == 'ROOT' and token.pos_ == 'VERB':
            entities['ACTION'] = token.lemma_
        elif token.dep_ in ['dobj', 'pobj'] and not entities['OBJECT']:
            entities['OBJECT'] = token.text
    
    # Extract keywords (nouns and proper nouns)
    entities['KEYWORDS'] = list(set([
        token.lemma_.lower() for token in spacy_doc 
        if token.pos_ in ['NOUN', 'PROPN'] and not token.is_stop and len(token.text) > 2
    ]))
    
    # Debug output
    print(f"Extracted Entities: {{'TASK': '{entities['TASK']}', 'TIME': '{entities['TIME']}', 'PARSED': {entities['TIME_PARSED']}, 'RECURRING': {entities['RECURRING']}}}")
    
    return entities


# =============================================================================
# INTENT & CLASSIFICATION FUNCTIONS
# =============================================================================

def classify_intent(text):
    """
    Classify the primary intent of the user's input.
    
    Args:
        text (str): User input text.
        
    Returns:
        dict: Intent classification with confidence scores.
    """
    text_lower = text.lower()
    scores = {}
    
    for intent, keywords in INTENT_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text_lower:
                # Boost score for longer matches
                score += len(kw.split())
                # Extra boost for exact matches at start
                if text_lower.startswith(kw):
                    score += 2
        if score > 0:
            scores[intent] = score
    
    if not scores:
        scores['chat'] = 1  # Default fallback
    
    # Sort by score
    sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    total_score = sum(scores.values())
    
    return {
        'primary_intent': sorted_intents[0][0],
        'confidence': sorted_intents[0][1] / total_score if total_score > 0 else 0,
        'all_intents': dict(sorted_intents),
        'is_ambiguous': len(sorted_intents) > 1 and sorted_intents[0][1] == sorted_intents[1][1] if len(sorted_intents) > 1 else False
    }


def classify_query_type(text):
    """
    Classify the type of query for better intent handling.
    
    Args:
        text (str): User input text.
        
    Returns:
        str: Query type ('question', 'command', 'statement', 'confirmation', 'denial', 'greeting', 'conversation')
    """
    text_lower = text.lower().strip()
    words = text_lower.split()
    
    if not words:
        return 'empty'
    
    first_word = words[0]
    
    # Check for confirmation/denial first
    if first_word in CONFIRMATION_WORDS or text_lower in CONFIRMATION_WORDS:
        return 'confirmation'
    if first_word in DENIAL_WORDS or text_lower in DENIAL_WORDS:
        return 'denial'
    
    # Check for greetings
    if any(g in text_lower for g in INTENT_KEYWORDS.get('greeting', [])):
        return 'greeting'
    
    # Check for questions
    if '?' in text or first_word in QUESTION_WORDS:
        return 'question'
    
    # Check for commands
    if first_word in COMMAND_VERBS or any(text_lower.startswith(v + ' ') for v in COMMAND_VERBS):
        return 'command'
    
    # Check for statements (declarative sentences)
    if spacy_doc := nlp(text):
        if spacy_doc[0].pos_ in ['PRON', 'PROPN', 'NOUN', 'DET']:
            return 'statement'
    
    return 'conversation'


def detect_urgency(text):
    """
    Detect the urgency level of a request.
    
    Args:
        text (str): User input text.
        
    Returns:
        dict: Urgency level and indicators found.
    """
    text_lower = text.lower()
    
    for level, words in URGENCY_WORDS.items():
        found = [w for w in words if w in text_lower]
        if found:
            return {
                'level': level,
                'indicators': found,
                'score': {'high': 3, 'medium': 2, 'low': 1}[level]
            }
    
    return {'level': 'normal', 'indicators': [], 'score': 2}


def detect_topic(text):
    """
    Detect the main topic category of the text.
    
    Args:
        text (str): User input text.
        
    Returns:
        dict: Topic detection results.
    """
    text_lower = text.lower()
    topic_scores = {}
    
    for topic, keywords in TOPIC_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            topic_scores[topic] = score
    
    if not topic_scores:
        return {'primary_topic': 'general', 'all_topics': {}, 'confidence': 0}
    
    sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
    
    return {
        'primary_topic': sorted_topics[0][0],
        'all_topics': dict(sorted_topics),
        'confidence': sorted_topics[0][1] / sum(topic_scores.values())
    }


# =============================================================================
# SENTIMENT & EMOTION ANALYSIS
# =============================================================================

def analyze_sentiment(text):
    """
    Analyze the sentiment of the text using TextBlob.
    
    Args:
        text (str): Input text.
        
    Returns:
        dict: Comprehensive sentiment analysis.
    """
    blob = TextBlob(text)
    polarity = blob.sentiment.polarity
    subjectivity = blob.sentiment.subjectivity
    
    # Determine sentiment category
    if polarity <= SENTIMENT_THRESHOLDS['very_negative']:
        category = 'very_negative'
    elif polarity <= SENTIMENT_THRESHOLDS['negative']:
        category = 'negative'
    elif polarity <= SENTIMENT_THRESHOLDS['neutral']:
        category = 'neutral'
    elif polarity <= SENTIMENT_THRESHOLDS['positive']:
        category = 'positive'
    else:
        category = 'very_positive'
    
    # Determine response tone suggestion
    if polarity < -0.3:
        suggested_tone = 'empathetic'
    elif polarity > 0.3:
        suggested_tone = 'enthusiastic'
    else:
        suggested_tone = 'neutral'
    
    return {
        'polarity': round(polarity, 3),
        'subjectivity': round(subjectivity, 3),
        'category': category,
        'is_positive': polarity > 0.1,
        'is_negative': polarity < -0.1,
        'is_neutral': -0.1 <= polarity <= 0.1,
        'is_objective': subjectivity < 0.4,
        'is_subjective': subjectivity > 0.6,
        'suggested_response_tone': suggested_tone
    }


def detect_emotion(text):
    """
    Detect emotional indicators in text.
    
    Args:
        text (str): Input text.
        
    Returns:
        dict: Detected emotions and their indicators.
    """
    text_lower = text.lower()
    detected = {}
    
    for emotion, indicators in EMOTION_PATTERNS.items():
        found = [i for i in indicators if i in text_lower]
        if found:
            detected[emotion] = {
                'indicators': found,
                'count': len(found)
            }
    
    if not detected:
        primary_emotion = 'neutral'
        intensity = 0
    else:
        primary_emotion = max(detected.keys(), key=lambda k: detected[k]['count'])
        intensity = detected[primary_emotion]['count']
    
    return {
        'primary_emotion': primary_emotion,
        'all_emotions': {k: v['indicators'] for k, v in detected.items()},
        'intensity': intensity,
        'emotional_state': 'calm' if intensity < 2 else ('moderate' if intensity < 4 else 'intense')
    }


# =============================================================================
# TEXT PROCESSING FUNCTIONS
# =============================================================================

def extract_numbers(text):
    """
    Extract all numbers from text (including written numbers).
    
    Args:
        text (str): Input text.
        
    Returns:
        list: List of extracted numbers as floats.
    """
    numbers = []
    
    # Extract digit numbers
    digit_pattern = r'-?\d+\.?\d*'
    for match in re.findall(digit_pattern, text):
        try:
            numbers.append(float(match))
        except ValueError:
            pass
    
    # Written number mapping
    written_numbers = {
        'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
        'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
        'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70,
        'eighty': 80, 'ninety': 90, 'hundred': 100, 'thousand': 1000, 'million': 1000000,
        'billion': 1000000000, 'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5,
        'half': 0.5, 'quarter': 0.25, 'dozen': 12, 'couple': 2, 'few': 3, 'several': 5
    }
    
    text_lower = text.lower()
    for word, num in written_numbers.items():
        if re.search(r'\b' + word + r'\b', text_lower):
            numbers.append(num)
    
    return list(set(numbers))  # Remove duplicates


def extract_keywords(text, top_n=10):
    """
    Extract important keywords from text using TF-IDF-like scoring.
    
    Args:
        text (str): Input text.
        top_n (int): Number of top keywords to return.
        
    Returns:
        list: List of (keyword, score) tuples.
    """
    doc = nlp(text)
    
    # Score words based on POS and other features
    word_scores = {}
    for token in doc:
        if token.is_stop or token.is_punct or len(token.text) < 2:
            continue
        
        score = 1
        # Boost nouns and proper nouns
        if token.pos_ in ['NOUN', 'PROPN']:
            score += 3
        # Boost verbs
        elif token.pos_ == 'VERB':
            score += 2
        # Boost adjectives
        elif token.pos_ == 'ADJ':
            score += 1
        # Boost named entities
        if token.ent_type_:
            score += 3
        # Boost capitalized words
        if token.text[0].isupper():
            score += 1
            
        word = token.lemma_.lower()
        word_scores[word] = word_scores.get(word, 0) + score
    
    sorted_keywords = sorted(word_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_keywords[:top_n]


def summarize_text(text, max_sentences=2):
    """
    Create a simple extractive summary of the text.
    
    Args:
        text (str): Input text.
        max_sentences (int): Maximum sentences in summary.
        
    Returns:
        str: Summarized text.
    """
    doc = nlp(text)
    sentences = list(doc.sents)
    
    if len(sentences) <= max_sentences:
        return text
    
    # Score sentences based on keyword density
    sentence_scores = []
    keywords = set([kw for kw, _ in extract_keywords(text, top_n=20)])
    
    for sent in sentences:
        score = sum(1 for token in sent if token.lemma_.lower() in keywords)
        # Boost first sentence
        if sent == sentences[0]:
            score += 2
        sentence_scores.append((sent.text, score, text.index(sent.text)))
    
    # Get top sentences maintaining order
    top_sentences = sorted(sentence_scores, key=lambda x: x[1], reverse=True)[:max_sentences]
    ordered = sorted(top_sentences, key=lambda x: x[2])
    
    return ' '.join([s[0] for s in ordered])


def normalize_text(text):
    """
    Normalize text for consistent processing.
    
    Args:
        text (str): Input text.
        
    Returns:
        str: Normalized text.
    """
    # Convert to lowercase
    normalized = text.lower()
    
    # Expand common contractions
    contractions = {
        "won't": "will not", "can't": "cannot", "n't": " not",
        "'re": " are", "'s": " is", "'d": " would", "'ll": " will",
        "'ve": " have", "'m": " am", "gonna": "going to",
        "wanna": "want to", "gotta": "got to", "kinda": "kind of",
        "lemme": "let me", "gimme": "give me", "dunno": "do not know",
        "y'all": "you all", "ain't": "is not", "cause": "because",
        "shoulda": "should have", "coulda": "could have", "woulda": "would have"
    }
    
    for contraction, expansion in contractions.items():
        normalized = normalized.replace(contraction, expansion)
    
    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized


def tokenize_smart(text):
    """
    Smart tokenization preserving important structures.
    
    Args:
        text (str): Input text.
        
    Returns:
        dict: Tokenization result with different granularities.
    """
    doc = nlp(text)
    
    return {
        'words': [token.text for token in doc if not token.is_space],
        'lemmas': [token.lemma_ for token in doc if not token.is_space],
        'sentences': [sent.text for sent in doc.sents],
        'noun_chunks': [chunk.text for chunk in doc.noun_chunks],
        'entities': [(ent.text, ent.label_) for ent in doc.ents],
        'pos_tags': [(token.text, token.pos_) for token in doc if not token.is_space],
        'dependencies': [(token.text, token.dep_, token.head.text) for token in doc]
    }


# =============================================================================
# SEMANTIC ANALYSIS
# =============================================================================

def calculate_similarity(text1, text2):
    """
    Calculate semantic similarity between two texts.
    
    Args:
        text1 (str): First text.
        text2 (str): Second text.
        
    Returns:
        float: Similarity score (0-1).
    """
    doc1 = nlp(text1)
    doc2 = nlp(text2)
    
    return doc1.similarity(doc2)


def find_similar_intent(text, known_intents):
    """
    Find the most similar intent using semantic similarity.
    
    Args:
        text (str): User input text.
        known_intents (dict): Dictionary of intent names to example phrases.
        
    Returns:
        tuple: (best_intent, similarity_score)
    """
    text_doc = nlp(text)
    
    best_intent = None
    best_score = 0
    
    for intent, examples in known_intents.items():
        for example in examples:
            example_doc = nlp(example)
            similarity = text_doc.similarity(example_doc)
            if similarity > best_score:
                best_score = similarity
                best_intent = intent
    
    return best_intent, best_score


def get_context_window(text, keyword, window_size=5):
    """
    Get surrounding context for a keyword.
    
    Args:
        text (str): Input text.
        keyword (str): Keyword to find context for.
        window_size (int): Number of words on each side.
        
    Returns:
        list: Context windows containing the keyword.
    """
    words = text.split()
    contexts = []
    
    for i, word in enumerate(words):
        if keyword.lower() in word.lower():
            start = max(0, i - window_size)
            end = min(len(words), i + window_size + 1)
            contexts.append(' '.join(words[start:end]))
    
    return contexts


def extract_relationships(text):
    """
    Extract relationships between entities in text.
    
    Args:
        text (str): Input text.
        
    Returns:
        list: List of (subject, verb, object) tuples.
    """
    doc = nlp(text)
    relationships = []
    
    for token in doc:
        if token.pos_ == 'VERB':
            subject = None
            obj = None
            
            for child in token.children:
                if child.dep_ in ['nsubj', 'nsubjpass']:
                    subject = child.text
                elif child.dep_ in ['dobj', 'pobj']:
                    obj = child.text
            
            if subject or obj:
                relationships.append({
                    'subject': subject,
                    'verb': token.lemma_,
                    'object': obj
                })
    
    return relationships


# =============================================================================
# HIGH-LEVEL HELPER FUNCTIONS
# =============================================================================

def parse_natural_time(time_text):
    """
    Parse natural language time expressions.
    
    Args:
        time_text (str): Natural language time like "in 30 minutes", "tomorrow at 5pm"
        
    Returns:
        datetime: Parsed datetime object or None
    """
    if not time_text:
        return None
        
    parsed = dateparser.parse(
        time_text,
        settings={
            'PREFER_DATES_FROM': 'future',
            'PREFER_DAY_OF_MONTH': 'first',
            'RETURN_AS_TIMEZONE_AWARE': False
        }
    )
    
    # Ensure future time
    if parsed and parsed < datetime.now():
        if parsed.date() == datetime.now().date():
            parsed += timedelta(days=1)
    
    return parsed


def extract_reminder_info(text):
    """
    High-level function specifically for reminder extraction.
    
    Args:
        text (str): User's reminder request.
        
    Returns:
        dict: Complete reminder information.
    """
    entities = extract_entities(text)
    
    # Try to parse time if not already parsed
    if entities['TIME'] and not entities['TIME_PARSED']:
        entities['TIME_PARSED'] = parse_natural_time(entities['TIME'])
    
    return {
        'task': entities['TASK'],
        'time': entities['TIME'],
        'datetime': entities['TIME_PARSED'],
        'recurring': entities['RECURRING'],
        'interval': entities['INTERVAL'],
        'location': entities['LOCATION'][0] if entities['LOCATION'] else None,
        'person': entities['PERSON'][0] if entities['PERSON'] else None,
        'urgency': detect_urgency(text),
        'valid': bool(entities['TASK'] and entities['TIME'])
    }


def analyze_query(text):
    """
    Comprehensive query analysis combining all NLP features.
    
    Args:
        text (str): User input text.
        
    Returns:
        dict: Complete analysis of the query.
    """
    # Normalize text
    normalized = normalize_text(text)
    
    # Get all analyses
    entities = extract_entities(text)
    intent = classify_intent(text)
    query_type = classify_query_type(text)
    sentiment = analyze_sentiment(text)
    emotion = detect_emotion(text)
    urgency = detect_urgency(text)
    topic = detect_topic(text)
    keywords = extract_keywords(text, top_n=5)
    numbers = extract_numbers(text)
    
    return {
        'original_text': text,
        'normalized_text': normalized,
        'entities': entities,
        'intent': intent,
        'query_type': query_type,
        'sentiment': sentiment,
        'emotion': emotion,
        'urgency': urgency,
        'topic': topic,
        'keywords': keywords,
        'numbers': numbers,
        'metadata': {
            'word_count': len(text.split()),
            'char_count': len(text),
            'sentence_count': len(list(nlp(text).sents)),
            'has_question': entities['HAS_QUESTION'],
            'has_negation': entities['HAS_NEGATION'],
            'is_confirmation': entities['IS_CONFIRMATION'],
            'is_denial': entities['IS_DENIAL'],
            'is_polite': entities['IS_POLITE']
        }
    }


def get_entities_summary(text):
    """
    Get a quick summary of all entities in text.
    
    Args:
        text (str): Input text.
        
    Returns:
        dict: Summary of all detected entities.
    """
    doc = nlp(text)
    
    return {
        'entities': [(ent.text, ent.label_) for ent in doc.ents],
        'nouns': [token.text for token in doc if token.pos_ == 'NOUN'],
        'verbs': [token.text for token in doc if token.pos_ == 'VERB'],
        'adjectives': [token.text for token in doc if token.pos_ == 'ADJ'],
        'adverbs': [token.text for token in doc if token.pos_ == 'ADV'],
        'query_type': classify_query_type(text),
        'intent': classify_intent(text)['primary_intent'],
        'sentiment': analyze_sentiment(text)['category']
    }


# =============================================================================
# CONVERSATION CONTEXT HELPERS
# =============================================================================

def resolve_pronouns(text, context):
    """
    Simple pronoun resolution based on conversation context.
    
    Args:
        text (str): Current input text.
        context (list): Previous conversation turns [(user, assistant), ...]
        
    Returns:
        str: Text with resolved pronouns where possible.
    """
    if not context:
        return text
    
    # Get recent entities from context
    recent_entities = {
        'person': None,
        'place': None,
        'thing': None
    }
    
    for user_text, _ in reversed(context[-3:]):
        entities = extract_entities(user_text)
        if entities['PERSON'] and not recent_entities['person']:
            recent_entities['person'] = entities['PERSON'][0]
        if entities['LOCATION'] and not recent_entities['place']:
            recent_entities['place'] = entities['LOCATION'][0]
        if entities['OBJECT'] and not recent_entities['thing']:
            recent_entities['thing'] = entities['OBJECT']
    
    # Replace pronouns (simple approach)
    resolved = text
    if recent_entities['person']:
        resolved = re.sub(r'\b(he|him|his|she|her|hers|they|them|their)\b', 
                         recent_entities['person'], resolved, flags=re.IGNORECASE)
    if recent_entities['place']:
        resolved = re.sub(r'\b(there|here)\b', 
                         recent_entities['place'], resolved, flags=re.IGNORECASE)
    if recent_entities['thing']:
        resolved = re.sub(r'\b(it|that|this|those|these)\b', 
                         recent_entities['thing'], resolved, flags=re.IGNORECASE)
    
    return resolved


def is_follow_up(text, context):
    """
    Determine if the current input is a follow-up to previous conversation.
    
    Args:
        text (str): Current input text.
        context (list): Previous conversation turns.
        
    Returns:
        dict: Follow-up detection result.
    """
    if not context:
        return {'is_follow_up': False, 'confidence': 0, 'indicators': []}
    
    follow_up_indicators = [
        'and', 'also', 'what about', 'how about', 'another', 'more',
        'else', 'too', 'as well', 'in addition', 'furthermore',
        'it', 'that', 'this', 'those', 'these', 'the same',
        'again', 'another one', 'one more', 'continue'
    ]
    
    text_lower = text.lower()
    found_indicators = []
    
    # Check for follow-up indicators
    for ind in follow_up_indicators:
        if text_lower.startswith(ind) or f' {ind} ' in f' {text_lower} ':
            found_indicators.append(ind)
    
    # Check for pronouns without clear reference
    if re.match(r'^(it|that|this|they|he|she|them)\b', text_lower):
        found_indicators.append('pronoun_reference')
    
    # Short responses are often follow-ups
    is_short = len(text.split()) <= 3
    if is_short:
        found_indicators.append('short_response')
    
    is_follow = len(found_indicators) > 0
    confidence = min(len(found_indicators) / 3, 1.0)
    
    return {
        'is_follow_up': is_follow,
        'confidence': confidence,
        'indicators': found_indicators
    }


def get_conversation_context(history, max_turns=5):
    """
    Extract relevant context from conversation history.
    
    Args:
        history (list): List of (user_input, assistant_response) tuples.
        max_turns (int): Maximum turns to consider.
        
    Returns:
        dict: Conversation context summary.
    """
    if not history:
        return {'topics': [], 'entities': [], 'last_intent': None}
    
    recent = history[-max_turns:]
    
    all_topics = []
    all_entities = []
    last_intent = None
    
    for user_text, _ in recent:
        topic = detect_topic(user_text)
        if topic['primary_topic'] != 'general':
            all_topics.append(topic['primary_topic'])
        
        entities = extract_entities(user_text)
        all_entities.extend(entities['PERSON'])
        all_entities.extend(entities['LOCATION'])
        all_entities.extend(entities['ORGANIZATION'])
        
        last_intent = classify_intent(user_text)['primary_intent']
    
    return {
        'topics': list(set(all_topics)),
        'entities': list(set(all_entities)),
        'last_intent': last_intent,
        'turn_count': len(recent)
    }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def validate_input(text):
    """
    Validate and clean user input.
    
    Args:
        text (str): User input text.
        
    Returns:
        dict: Validation result with cleaned text.
    """
    issues = []
    cleaned = text.strip()
    
    # Check for empty input
    if not cleaned:
        return {'valid': False, 'issues': ['empty_input'], 'cleaned': ''}
    
    # Check for very short input
    if len(cleaned) < 2:
        issues.append('too_short')
    
    # Check for excessive length
    if len(cleaned) > 1000:
        issues.append('too_long')
        cleaned = cleaned[:1000]
    
    # Check for repeated characters (spam detection)
    if re.search(r'(.)\1{5,}', cleaned):
        issues.append('repeated_chars')
        cleaned = re.sub(r'(.)\1{5,}', r'\1\1\1', cleaned)
    
    # Check for all caps (shouting)
    if cleaned.isupper() and len(cleaned) > 10:
        issues.append('all_caps')
        cleaned = cleaned.lower()
    
    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'cleaned': cleaned
    }


def format_response_context(analysis):
    """
    Generate context for response generation based on query analysis.
    
    Args:
        analysis (dict): Result from analyze_query().
        
    Returns:
        dict: Context for response generation.
    """
    return {
        'should_be_formal': analysis['entities']['IS_POLITE'],
        'tone': analysis['sentiment']['suggested_response_tone'],
        'urgency_level': analysis['urgency']['level'],
        'is_question': analysis['entities']['HAS_QUESTION'],
        'requires_confirmation': analysis['query_type'] == 'command',
        'emotional_support_needed': analysis['emotion']['primary_emotion'] in ['sad', 'angry', 'fearful'],
        'topic': analysis['topic']['primary_topic'],
        'intent': analysis['intent']['primary_intent']
    }
