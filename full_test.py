import unittest
from unittest.mock import patch, MagicMock
from core.intent_handler import handle_query
from core.memory_manager import initialize_memory, get_recent_conversations, set_user_preference, get_user_preference, set_session_data, get_session_data
from core.weather_service import get_weather
from core.chatgpt_service import get_chatgpt_response

class TestJervisProject(unittest.TestCase):

    def setUp(self):
        """Set up the initial environment for the tests."""
        # Initialize the database to ensure tables are present
        initialize_memory()
        # Setting a default preference
        set_user_preference("default_location", "Helsinki")

    @patch('core.speech_synthesis.synthesize_speech')
    def test_weather_query(self, mock_speech):
        """Test weather query and response."""
        with patch('core.weather_service.get_weather') as mock_weather:
            mock_weather.return_value = "The weather in Helsinki is sunny and 20°C."
            query = "What is the weather?"
            result = handle_query(query)
            mock_speech.assert_called_with("The weather in Helsinki is sunny and 20°C.")
            self.assertTrue(result)

    @patch('core.speech_synthesis.synthesize_speech')
    def test_set_location(self, mock_speech):
        """Test setting a new default location."""
        query = "Set my location to Kokkola"
        result = handle_query(query)
        updated_location = get_user_preference("default_location")
        self.assertEqual(updated_location, "Kokkola")
        mock_speech.assert_called_with("Location set to Kokkola.")
        self.assertTrue(result)

    @patch('core.speech_synthesis.synthesize_speech')
    def test_hourly_climate_query(self, mock_speech):
        """Test hourly climate query, simulating a multi-step interaction."""
        # Setting pending hour to a specific value
        set_session_data("pending_hour", "15")
        query = "What's the hourly climate?"
        result = handle_query(query)
        mock_speech.assert_called_with("The average temperature for hour 15 is 20°C.")
        self.assertTrue(result)

    @patch('core.speech_synthesis.synthesize_speech')
    def test_multi_step_preference_setting(self, mock_speech):
        """Test multi-step preference setting process."""
        # Step 1: Initiate preference setting
        query = "I want to set a preference"
        handle_query(query)
        mock_speech.assert_called_with("What preference would you like to set?")
        step = get_session_data("preference_setting_step")
        self.assertEqual(step, "awaiting_key")

        # Step 2: Provide preference key
        query = "default_language"
        handle_query(query)
        mock_speech.assert_called_with("Got it. Now, tell me the value for this preference.")
        step = get_session_data("preference_setting_step")
        self.assertEqual(step, "awaiting_value")
        key = get_session_data("preference_key")
        self.assertEqual(key, "default_language")

        # Step 3: Provide preference value
        query = "English"
        handle_query(query)
        mock_speech.assert_called_with("Preference default_language set to English.")
        step = get_session_data("preference_setting_step")
        self.assertIsNone(step)
        value = get_user_preference("default_language")
        self.assertEqual(value, "English")

    @patch('core.speech_synthesis.synthesize_speech')
    def test_google_search_intent(self, mock_speech):
        """Test handling of the 'google' intent."""
        with patch('webbrowser.open') as mock_browser:
            query = "Open Google"
            result = handle_query(query)
            mock_browser.assert_called_with("https://www.google.com")
            mock_speech.assert_called_with("Opening Google.")
            self.assertTrue(result)

    @patch('core.speech_synthesis.synthesize_speech')
    def test_thank_you_response(self, mock_speech):
        """Test responding to a thank-you intent."""
        query = "Thank you, Jervis"
        result = handle_query(query)
        self.assertTrue(result)
        self.assertTrue(mock_speech.called)  # Ensure any thank-you response is fine

    @patch('core.speech_synthesis.synthesize_speech')
    def test_fallback_to_chatgpt(self, mock_speech):
        """Test fallback response using ChatGPT for unknown queries."""
        with patch('core.chatgpt_service.get_chatgpt_response') as mock_chatgpt:
            mock_chatgpt.return_value = "Here is some information that might help."
            query = "How do planes fly?"
            result = handle_query(query)
            mock_speech.assert_called_with("Here is some information that might help.")
            self.assertTrue(result)

    @patch('core.speech_synthesis.synthesize_speech')
    def test_cross_session_context(self, mock_speech):
        """Test if Jervis can remember information across multiple sessions."""
        # Set user preference in one session
        query = "Set my location to Espoo"
        handle_query(query)
        updated_location = get_user_preference("default_location")
        self.assertEqual(updated_location, "Espoo")
        mock_speech.assert_called_with("Location set to Espoo.")

        # Check if Jervis remembers in a new interaction
        query = "What is my location?"
        result = handle_query(query)
        mock_speech.assert_called_with("Your default location is set to Espoo.")
        self.assertTrue(result)

if __name__ == "__main__":
    unittest.main()
