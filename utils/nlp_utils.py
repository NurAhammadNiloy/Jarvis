import spacy

nlp = spacy.load("en_core_web_trf")

def extract_entities(doc):
    """
    Extract entities from the user query using spaCy.
    
    Args:
        doc (spacy.tokens.Doc): The parsed doc object.
        
    Returns:
        dict: A dictionary containing the extracted entities.
    """
    entities = {
        'TASK': '',
        'TIME': None
    }
    
    for ent in doc.ents:
        if ent.label_ == 'TIME' or ent.label_ == 'DATE':
            entities['TIME'] = ent.text
        elif ent.label_ in ['EVENT', 'PERSON', 'ORG', 'WORK_OF_ART', 'PRODUCT']:
            entities['TASK'] += ' ' + ent.text if entities['TASK'] else ent.text
    
    # Debug: Print extracted entities
    print("Extracted Entities:", entities)
    
    # Fallback to entire sentence as task if nothing was recognized
    if not entities['TASK']:
        entities['TASK'] = doc.text.strip()

    return entities
