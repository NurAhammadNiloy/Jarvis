import openai
from config.api_keys import OPENAI_API_KEY

openai.api_key = OPENAI_API_KEY

def get_chatgpt_response(history):
    try:
        # Adding system message to control response style
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Please respond with short, conversational answers."},  # System instruction
                {"role": "user", "content": history}
            ],
            temperature=0.3,  # Control randomness (keep it focused)
            max_tokens=80     # Limit the length of the response
        )
        return response['choices'][0]['message']['content']
    except Exception as e:
        print(f"Error with ChatGPT: {e}")
        return "I'm sorry, I couldn't get a response from ChatGPT."
