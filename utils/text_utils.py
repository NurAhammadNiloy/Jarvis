import re

def clean_text(text):
    """
    Clean and preprocess a given text string.
    
    Args:
        text (str): The text to be cleaned.
    
    Returns:
        str: The cleaned text.
    """
    text = re.sub(r'\s+', ' ', text)  # Replace multiple spaces with a single space
    text = text.strip()  # Remove leading and trailing spaces
    return text

def contains_word(query, word):
    """
    Check if a specific word is in a given query.
    
    Args:
        query (str): The text to search within.
        word (str): The word to search for.
    
    Returns:
        bool: True if the word is found, False otherwise.
    """
    return bool(re.search(rf'\b{word}\b', query, re.IGNORECASE))
