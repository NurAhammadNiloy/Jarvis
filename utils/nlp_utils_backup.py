import spacy
import re
import dateparser
from datetime import datetime, timedelta

nlp = spacy.load("en_core_web_trf")

# Time extraction patterns (ordered by specificity)
TIME_PATTERNS = [
    # Specific times with AM/PM
    r'(?:at\s+)?(\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.))',
    r'(?:at\s+)?(\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.))',
    # 24-hour format
    r'(?:at\s+)?(\d{1,2}:\d{2})',
    # Relative times
    r'(in\s+\d+\s*(?:minute|min|minutes|mins|hour|hours|hr|hrs|day|days|week|weeks)s?)',
    # Named times
    r'(tonight|tomorrow|today|this\s+(?:morning|afternoon|evening|night))',
    r'(tomorrow\s+(?:morning|afternoon|evening|night))',
    r'(next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month))',
    # Date patterns
    r'(?:on\s+)?(\w+\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)',
    r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?\w+)',
]

# Patterns to remove from task extraction
REMOVE_PATTERNS = [
    r'^remind\s+me\s+to\s+',
    r'^set\s+(?:a\s+)?reminder\s+(?:to\s+|for\s+)?',
    r'^reminder\s+(?:to\s+|for\s+)?',
    r'^please\s+remind\s+me\s+to\s+',
    r'^can\s+you\s+remind\s+me\s+to\s+',
    r'^i\s+need\s+(?:a\s+)?reminder\s+(?:to\s+|for\s+)?',
    r'\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?',
    r'\s+at\s+\d{1,2}(?::\d{2})?',
    r'\s+in\s+\d+\s*(?:minute|min|minutes|mins|hour|hours|hr|hrs|day|days)s?',
    r'\s+(?:on\s+)?tomorrow(?:\s+(?:morning|afternoon|evening|night))?',
    r'\s+(?:on\s+)?today',
    r'\s+(?:on\s+)?tonight',
    r'\s+(?:on\s+)?this\s+(?:morning|afternoon|evening|night)',
    r'\s+(?:on\s+)?next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month)',
]

# Keywords that indicate a reminder/task intent
REMINDER_KEYWORDS = ['remind', 'reminder', 'alert', 'notify', 'schedule']


def extract_time_from_text(text):
    """
    Extract time/date information from text using regex and dateparser.
    
    Args:
        text (str): The input text to parse.
        
    Returns:
        tuple: (extracted_time_str, parsed_datetime or None)
    """
    text_lower = text.lower().strip()
    
    # Try regex patterns first
    for pattern in TIME_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            time_str = match.group(1).strip()
            # Try to parse with dateparser
            parsed = dateparser.parse(
                time_str,
                settings={
                    'PREFER_DATES_FROM': 'future',
                    'PREFER_DAY_OF_MONTH': 'first',
                    'RETURN_AS_TIMEZONE_AWARE': False
                }
            )
            if parsed:
                return time_str, parsed
            return time_str, None
    
    # Fallback: Try dateparser on segments of the text
    words = text_lower.split()
    for i in range(len(words)):
        for j in range(i + 1, min(i + 5, len(words) + 1)):
            segment = ' '.join(words[i:j])
            parsed = dateparser.parse(
                segment,
                settings={
                    'PREFER_DATES_FROM': 'future',
                    'RETURN_AS_TIMEZONE_AWARE': False
                }
            )
            if parsed and parsed > datetime.now():
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
    task = text.lower().strip()
    
    # Remove command prefixes
    for pattern in REMOVE_PATTERNS:
        task = re.sub(pattern, ' ', task, flags=re.IGNORECASE)
    
    # Remove the specific time string if found
    if time_str:
        task = task.replace(time_str.lower(), '')
    
    # Clean up extra whitespace
    task = re.sub(r'\s+', ' ', task).strip()
    
    # Remove leading/trailing prepositions
    task = re.sub(r'^(?:to|for|about|that)\s+', '', task)
    task = re.sub(r'\s+(?:at|on|in|for)$', '', task)
    
    return task.strip()


def extract_entities(doc):
    """
    Extract entities from the user query using spaCy + regex + dateparser.
    
    Args:
        doc (spacy.tokens.Doc): The parsed doc object.
        
    Returns:
        dict: A dictionary containing the extracted entities.
    """
    text = doc.text if hasattr(doc, 'text') else str(doc)
    
    entities = {
        'TASK': '',
        'TIME': None,
        'TIME_PARSED': None,
        'RECURRING': False,
        'INTERVAL': None,
        'LOCATION': None,
        'PERSON': None
    }
    
    # Check for recurring patterns
    recurring_patterns = {
        'daily': r'\b(?:every\s*day|daily|each\s*day)\b',
        'weekly': r'\b(?:every\s*week|weekly|each\s*week)\b',
        'hourly': r'\b(?:every\s*hour|hourly|each\s*hour)\b',
        'monthly': r'\b(?:every\s*month|monthly|each\s*month)\b',
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
    task = extract_task_from_text(text, time_str)
    
    # Use spaCy for additional entity extraction
    spacy_doc = nlp(text) if isinstance(doc, str) else doc
    
    for ent in spacy_doc.ents:
        if ent.label_ in ['TIME', 'DATE'] and not entities['TIME']:
            entities['TIME'] = ent.text
            # Try to parse spaCy-extracted time
            parsed = dateparser.parse(
                ent.text,
                settings={'PREFER_DATES_FROM': 'future'}
            )
            if parsed:
                entities['TIME_PARSED'] = parsed
                
        elif ent.label_ == 'GPE' or ent.label_ == 'LOC':
            entities['LOCATION'] = ent.text
            
        elif ent.label_ == 'PERSON':
            entities['PERSON'] = ent.text
            # Add person to task if relevant
            if ent.text.lower() not in task.lower():
                task = f"{task} {ent.text}".strip()
                
        elif ent.label_ in ['EVENT', 'WORK_OF_ART', 'PRODUCT', 'ORG']:
            # Add to task if not already present
            if ent.text.lower() not in task.lower():
                task = f"{task} {ent.text}".strip()
    
    # Set the final task
    entities['TASK'] = task if task else text.strip()
    
    # Debug output
    print(f"Extracted Entities: {{'TASK': '{entities['TASK']}', 'TIME': '{entities['TIME']}', 'PARSED': {entities['TIME_PARSED']}, 'RECURRING': {entities['RECURRING']}}}")
    
    return entities


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
        # If time is in the past, assume next occurrence
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
    doc = nlp(text)
    entities = extract_entities(doc)
    
    # Try to parse time if not already parsed
    if entities['TIME'] and not entities['TIME_PARSED']:
        entities['TIME_PARSED'] = parse_natural_time(entities['TIME'])
    
    return {
        'task': entities['TASK'],
        'time': entities['TIME'],
        'datetime': entities['TIME_PARSED'],
        'recurring': entities['RECURRING'],
        'interval': entities['INTERVAL'],
        'location': entities['LOCATION'],
        'person': entities['PERSON'],
        'valid': bool(entities['TASK'] and entities['TIME'])
    }


def classify_query_type(text):
    """
    Classify the type of query for better intent handling.
    
    Args:
        text (str): User input text.
        
    Returns:
        str: Query type ('reminder', 'question', 'command', 'conversation')
    """
    text_lower = text.lower()
    
    if any(kw in text_lower for kw in REMINDER_KEYWORDS):
        return 'reminder'
    elif text_lower.startswith(('what', 'when', 'where', 'who', 'why', 'how', 'is', 'are', 'can', 'do', 'does')):
        return 'question'
    elif text_lower.startswith(('play', 'open', 'start', 'stop', 'turn', 'set', 'show')):
        return 'command'
    else:
        return 'conversation'


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
        'query_type': classify_query_type(text)
    }
