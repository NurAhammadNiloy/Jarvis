import openai
from config.api_keys import OPENAI_API_KEY

openai.api_key = OPENAI_API_KEY

def get_chatgpt_response(history):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": history}]
        )
        return response['choices'][0]['message']['content']
    except Exception as e:
        print(f"Error with ChatGPT: {e}")
        return "I'm sorry, I couldn't get a response from ChatGPT."
