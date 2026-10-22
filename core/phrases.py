"""Everything Jarvis says in fixed words, in one place. Edit freely.

Each entry is a list of variants; one is picked at random each time, so common
replies don't sound canned. {name} placeholders are filled in by the code; keep
the same names when you rewrite a line.

Style: short, warm and natural, like a capable human assistant with a light
JARVIS touch. Most action replies stay under eight words. Say what was done,
not what you heard. No filler ("I'll keep an eye on it for you", "Let me know if
there's anything else").
"""
import random

# Roughly how often a reply that allows it gets a "sir" (1 in 5).
SIR_RATE = 0.2

PHRASES = {
    # --- conversation -------------------------------------------------------
    'greeting': ['Yes?', 'How can I help?', "I'm listening.", 'At your service.'],
    'not_heard': ['Sorry?', 'Say again?', 'Come again?'],
    'not_heard_then': ['Sorry? {question}', 'Say again? {question}'],
    'repeat_please': ['Sorry, say that again?', 'Say that once more?', 'One more time?'],
    'incomplete': ['Sorry, I missed the end. Again?', 'You cut out. Again?'],
    'cancelled': ['Cancelled.', 'Okay, cancelled.', 'Never mind, then.'],
    'okay': ['Okay.', 'Alright.', 'Sure.'],
    'what_to_do': ['What should I do?', 'What do you need?'],
    'model_failed': ['Sorry, I lost my train of thought. Say that again?'],
    'claim_fallback': ["I haven't done that yet. What should I do?"],
    'cannot_work_out': ['Sorry, I didn\'t get what to do. Say it again?'],
    'reask': ['Sorry? Should I go ahead?'],          # must never contain "yes"
    'declined': ["Okay, I won't.", 'Okay, leaving it.'],
    'which_one': ['Sorry, which one? {question}'],
    'which_timer': ['Which one: {timers}?'],
    'not_sure_then': ['Sorry? {question}', 'Didn\'t catch that. {question}'],
    'wont_act': ["I won't do that. What do you want?"],
    'control_what': ['{verb} what?'],
    'mean_timer': ['A timer?'],
    'repeat_to_confirm': ['{text}? Say it again to confirm.'],
    'thanks': ["You're welcome.", 'Anytime.', 'Happy to help.', 'My pleasure.'],

    # --- undo -----------------------------------------------------------------
    'undone': ['Undone.'],
    'nothing_to_undo': ['Nothing to undo.', "There's nothing to undo."],
    'cannot_undo': ["Sorry, I can't undo that."],
    'undo_failed': ["Sorry, I couldn't undo that."],

    # --- playback I can't control ---------------------------------------------
    'no_media_control': ["I can't control YouTube playback yet."],

    # --- time and date --------------------------------------------------------
    'time': ["It's {time}.", '{time}.'],
    'date_today': ["It's {date}.", 'Today is {date}.'],
    'date_tomorrow': ['Tomorrow is {date}.'],
    'date_yesterday': ['Yesterday was {date}.'],
    'date_day_after': ['The day after tomorrow is {date}.'],

    # --- weather and follow-ups ---------------------------------------------
    'which_city': ['Which city?', 'For which city?'],
    'glad': ['Glad to help.', 'Good.'],
    'play_what': ['What should I play?'],
    'enjoy': ['Enjoy.', 'Enjoy it.'],
    'more_about_what': ['More about what?'],

    # --- web --------------------------------------------------------------------
    'playing': ['Playing {topic}.', 'Here’s {topic}.'],
    'opening_youtube': ['Opening YouTube.'],
    'youtube_not_found': ["Couldn't find {topic} on YouTube."],
    'opening_google': ['Opening Google.', 'Google, coming up.'],
    'no_browser': ["I couldn't open your browser."],

    # --- timers -----------------------------------------------------------------
    'timer_set': ['{name} timer, {duration}.', '{duration} on the {name} timer.', '{name} timer started: {duration}.'],
    'timer_set_plain': ['Timer, {duration}.', '{duration}, starting now.', 'Timer set: {duration}.'],
    'timer_paused': ['Paused. {left} left.', '{name} paused, {left} left.'],
    'timer_resumed': ['Resumed. {left} left.', 'Back on: {left} to go.'],
    'timer_cancelled': ['{name} timer cancelled.', 'Cancelled the {name} timer.'],
    'timer_cancelled_plain': ['Timer cancelled.', 'Cancelled.'],
    'timers_all_cancelled': ['All {count} timers cancelled.', 'Cancelled all {count} timers.'],
    'no_timers': ['No timers running.', 'There are no timers.'],
    'time_added': ['Added {duration} to {name}.', '{name}: {duration} more.'],
    'time_added_plain': ['Added {duration}.', '{duration} more on the timer.'],
    'time_removed': ['Took {duration} off {name}.', '{name}: {duration} less.'],
    'time_removed_plain': ['Took {duration} off.', '{duration} less on the timer.'],
    'remove_too_much': ['Only {left} left on {name}.'],
    'remove_how_much': ['How much time should I take off?'],
    'wont_cancel': ["Okay, I won't cancel it.", 'Okay, leaving it.'],
    'undo_hint': ['Say undo to bring it back.'],
    'timer_status': ['{name}: {left} left.', '{left} left on {name}.'],
    'timer_status_plain': ['{left} left.', '{left} to go.'],
    'timer_status_paused': ['{name} is paused, {left} left.'],
    'timer_status_many': ['{count} timers: {list}.'],
    'timer_done': ["{name}'s done.", 'Your {name} timer is up.'],
    'timer_done_plain': ["Time's up.", "Timer's done."],
    'timer_milestone': ['{name}: {message}.'],
    'timer_milestone_plain': ['Timer: {message}.'],
    'timer_which': ['You have multiple timers. Which one should I {verb}?'],  # the code matches this wording
    'timer_not_found': ["I can't find {what}."],
    'timer_not_running': ["That timer isn't running."],
    'timer_not_paused': ["That timer isn't paused."],
    'timer_none_to': ['No timers to {verb}.'],
    'timer_no_duration': ['For how long?', 'How long should it run?'],
    'timer_zero': ['A timer needs more than zero time.'],
    'add_how_much': ['How much time should I add?'],
    'timer_next': ['Next timer starting.'],
    'pomodoro_started': ['Pomodoro {number}: focus for {work} minutes, then a {rest}-minute {kind}.'],
    'all_timers_cancelled': ['All timers cancelled.'],
    'timers_keep_running': ['Okay, they keep running.'],

    # --- reminders and alarms ---------------------------------------------------
    'reminder_set': ['Done, reminding you {when}: {task}.', 'Got it: {task} {when}.', 'Reminder set: {task} {when}.'],
    'alarm_set': ['Alarm set for {when}.', 'Done, alarm for {when}.'],
    'alarm_set_named': ['Alarm set for {when}: {label}.'],
    'reminder_due': ['Time to {task}.', 'Reminder: {task}.'],
    'reminder_due_noun': ['Reminder: {task}.', 'Heads up: {task}.'],
    'reminder_due_plain': ["Here's your reminder."],
    'alarm_due': ["It's {time} — your alarm."],
    'alarm_due_named': ["It's {time} — your alarm: {label}."],
    'reminder_missed': ['While I was off, you missed a reminder {when}: {task}.'],
    'alarm_missed': ['While I was off, your alarm {when} went off.'],
    'no_reminders': ['No {noun}s.', "You don't have any {noun}s."],
    'reminders_heading': ['You have {count} {noun}{s}.'],  # the count comes first, then the items
    'reminder_deleted': ['Deleted: {label}, {when}.'],
    'reminders_all_cancelled': ['All {count} {noun}s cancelled.'],
    'reminder_snoozed': ["Snoozed. I'll remind you {when}.", 'Snoozed until {time}.'],
    'reminder_not_found': ["I can't find a {noun} about {target}."],
    'reminder_not_found_plain': ["I can't find that {noun}."],
    'reminder_which': ['I found {count} {noun}s: {options}. Which one should I {verb}?'],
    # Questions about a missing time: keep ONE variant each - the code compares a
    # new question with the one it asked to see whether an answer made progress.
    'ask_reminder_time': ['When should I remind you?'],
    'ask_reminder_task': ['What should I remind you about?'],
    'ask_alarm_time': ['What time should I set the alarm for?'],
    'ask_time_for': ['What time should I set the {noun} for?'],
    'ask_when_for': ['When should I set the {noun} for?'],
    'ask_date_for': ['Which date should I set the {noun} for?'],
    'time_passed_today': ['That time has already passed today. When should I set the {noun} for?'],
    'time_passed': ['That time has already passed. When should I set the {noun} for?'],
    'am_or_pm': ['Did you mean {time} a.m. or p.m.?'],
    'reminder_unclear': ["Sorry, what's the reminder, and when?"],
    'startup_pending': ['You have {count} pending: {items}.'],
    'startup_pending_many': ['You have {count} pending. The next is {item}.'],
    # --- weather ----------------------------------------------------------------
    # Short answers to "should I wear a jacket?", "do I need an umbrella?", "should I go out?":
    # one sentence with the key reason. Full details only when they are asked for.
    'adv_wear': ['{item}: {reason}.'],
    'adv_item_thermal': ['Heavy coat and warm layers'],
    'adv_item_heavy': ['Warm winter coat'],
    'adv_item_winter': ['Winter jacket'],
    'adv_item_warm': ['Warm jacket'],
    'adv_item_light': ['Light jacket'],
    'adv_item_none': ['No jacket needed'],
    'adv_and_windy': [' and windy'],
    'adv_and_breezy': [' and breezy'],
    'adv_and_rainy': [' and rainy'],
    'adv_and_snowy': [' and snowy'],
    'adv_feels': [', feels like {temp}'],
    'adv_umbrella_yes': ['Yes: {weather}.'],
    'adv_umbrella_no': ['No: {weather}.'],
    'adv_umbrella_snow': ['Not for snow: {weather}.'],
    'adv_go_yes': ['Yes: {temp}, {weather}.'],
    'adv_go_bundle': ['Bundle up: {temp}, {weather}.'],
    'adv_go_stay': ['Better to stay in: {temp}.'],
    'adv_go_wait': ['Better wait: {weather}.'],

    # Current weather, short.
    'weather_brief_extreme': ["It's extremely cold in {city}. {temp}{feels}, {weather}."],
    'weather_brief_very_cold': ['Very cold in {city}. {temp}{feels}, {weather}.'],
    'weather_brief_freezing': ['Freezing in {city}. {temp}, {weather}.'],
    'weather_brief_cool': ["It's cool in {city}. {temp}, {weather}."],
    'weather_brief_mild': ['Mild weather in {city}. {temp}, {weather}.'],
    'weather_brief_pleasant': ['Pleasant {temp} in {city}, {weather}.'],
    'weather_brief_hot': ["It's hot in {city}. {temp}, {weather}."],

    # Current weather, in full (asked for with "tell me about", "in detail", "everything").
    'weather_go_no': ["I wouldn't recommend going out right now."],
    'weather_go_bundle': ['Only if you bundle up really well.'],
    'weather_go_dress': ['You can, but dress warmly.'],
    'weather_go_lovely': ["It's lovely outside."],
    'weather_go_wait': ["I'd wait a bit. The weather isn't ideal."],
    'weather_go_decent': ["It's decent outside."],
    'weather_wear_opener': ['For {city} right now,'],
    'weather_temp_opener': ["It's {temp} in {city}{feels}."],
    'weather_context': ["It's {temp} in {city}{feels}, with {weather}."],
    'weather_d_dangerous': ["It's dangerously cold in {city} right now. {temp}{feels}."],
    'weather_d_conditions': ['Current conditions: {weather}.'],
    'weather_d_indoors': ['I strongly advise staying indoors unless absolutely necessary.'],
    'weather_d_very_cold': ["It's very cold in {city} this {part}. {temp}{feels}, with {weather}."],
    'weather_d_freezing': ['Freezing temperatures in {city}. Currently {temp}{feels}, with {weather}.'],
    'weather_d_cool': ["It's quite cool in {city}. {temp}{feels}, with {weather}."],
    'weather_d_lovely': ['Lovely weather in {city} this {part}. {temp} with {weather}.'],
    'weather_d_mild': ['Mild conditions in {city}. {temp} with {weather}.'],
    'weather_d_warm': ['Warm weather in {city}. {temp} with {weather}.'],
    'weather_d_hot': ["It's hot in {city} today. {temp}{feels}, with {weather}."],
    'weather_wind': ["It's {wind} at {speed} meters per second."],
    'weather_vis_poor': ['Visibility is very poor. Be careful if driving.'],
    'weather_vis_reduced': ['Visibility is somewhat reduced.'],
    'weather_humid_high': ['The humidity is high, so it might feel muggy.'],
    'weather_dry': ['The air is quite dry.'],
    'weather_humidity_cloud': ['Humidity is at {humidity}%, and cloud cover is {clouds}%.'],
    'weather_recommend_one': ["I'd recommend {items}."],
    'weather_recommend_many': ["I'd recommend {items}, and {last}."],

    # Pieces of those sentences (said with part(), so they are not capitalized).
    'temp_zero': ['0 degrees'],
    'temp_one': ['{n} degree'],
    'temp_many': ['{n} degrees'],
    'feels_much_colder': [', but it feels much colder at {temp} due to wind chill'],
    'feels_colder': [', feels like {temp}'],
    'feels_much_warmer': [', but it feels much warmer at {temp}'],
    'feels_warmer': [', feels like {temp}'],
    'wind_calm': ['calm'],
    'wind_light': ['a light breeze'],
    'wind_moderate': ['a moderate breeze'],
    'wind_quite': ['quite windy'],
    'wind_very': ['very windy'],
    'wind_extreme': ['extremely windy with strong gusts'],
    'wear_thermal': ['thermal layers'],
    'wear_heavy_coat': ['a heavy winter coat'],
    'wear_boots_insulated': ['insulated boots'],
    'wear_gloves': ['gloves'],
    'wear_hat_warm': ['a warm hat'],
    'wear_scarf': ['a scarf covering your face'],
    'wear_layers': ['multiple layers'],
    'wear_winter_coat': ['a warm winter coat'],
    'wear_boots_warm': ['warm boots'],
    'wear_hat': ['a hat'],
    'wear_winter_jacket': ['a winter jacket'],
    'wear_warm_layers': ['warm layers'],
    'wear_warm_jacket': ['a warm jacket or coat'],
    'wear_light_jacket': ['a light jacket or sweater'],
    'wear_breathable': ['light, breathable clothing'],
    'wear_umbrella': ['an umbrella'],
    'wear_boots_waterproof': ['waterproof boots'],
    'wear_windbreaker': ['a windbreaker'],
    'activity_indoors_book': ['Perfect weather for a warm drink and a good book indoors.'],
    'activity_winter_walk': ["Great for a quick winter walk if you're bundled up."],
    'activity_cozy': ['A cozy day to stay warm inside.'],
    'activity_indoor': ['Good weather for indoor activities.'],
    'activity_brisk': ['Nice for a brisk walk with a warm jacket.'],
    'activity_outdoor': ['Perfect weather for outdoor activities.'],
    'activity_walk': ['Great for a walk or outdoor exercise.'],
    'activity_save_plans': ['Maybe save the outdoor plans for later.'],
    'activity_hydrated': ["Stay hydrated if you're heading out."],
    'activity_evening': ['A pleasant evening to be outside.'],
    'part_morning': ['morning'],
    'part_afternoon': ['afternoon'],
    'part_evening': ['evening'],
    'part_night': ['night'],

    # Forecast.
    'forecast_intro': ["Here's the outlook for {city}."],
    'forecast_day': ['{day} will be {feel}, {temp}, and {note}.'],
    'forecast_today': ['Today'],
    'forecast_around': ['around {n} degrees'],
    'forecast_between': ['between {low} and {high} degrees'],
    'forecast_dangerous': ['dangerously cold'],
    'forecast_very_cold': ['very cold'],
    'forecast_chilly': ['quite chilly'],
    'forecast_cool': ['cool'],
    'forecast_pleasant': ['pleasant'],
    'forecast_warm': ['warm'],
    'forecast_snow': ['expect some snow'],
    'forecast_rain': ['bring an umbrella'],
    'forecast_clear': ['skies will be clear'],
    'forecast_cloud': ["it'll be cloudy"],
    'forecast_bundle': ["Bundle up warmly if you're heading out this week."],
    'forecast_umbrella': ['Keep an umbrella handy.'],
    'forecast_winter': ["Looks like we'll have some winter weather."],
    'forecast_none': ["I couldn't get forecast data for {city}."],
    'forecast_failed': ["I couldn't get the forecast for {city}."],
    'forecast_connect': ["I'm having trouble getting the forecast right now."],

    # Weather problems.
    'weather_not_found': ["I couldn't find weather data for {city}. Could you check the spelling?"],
    'weather_auth': ["There's an issue with the weather service authentication. Please check the API key."],
    'weather_http': ["The weather service returned an error ({status}). Try again later."],
    'weather_timeout': ['The weather service took too long to respond. Please try again.'],
    'weather_connect': ["I'm having trouble connecting to the weather service right now. Please try again in a moment."],
    'compare_warmer': ['{warm} is {diff} warmer than {cool}.'],
    'compare_same': ['Both cities are at the same temperature.'],
    'compare_line': ['{city1}: {temp1} with {weather1}. {city2}: {temp2} with {weather2}. {comparison}'],
    'compare_failed': ["I couldn't compare the weather between {city1} and {city2}."],
}

# Replies that may get a "sir" now and then.
SIR_OK = {'greeting', 'timer_set', 'timer_set_plain', 'reminder_set', 'alarm_set', 'timer_done',
          'timer_done_plain', 'reminder_due', 'reminder_due_noun', 'alarm_due', 'thanks', 'okay',
          'cancelled', 'opening_google', 'playing'}

_choose = random.choice
_random = random.random


def say(key, **values):
    """One variant of a phrase with its placeholders filled in."""
    text = _choose(PHRASES[key]).format(**values)
    text = text[:1].upper() + text[1:]
    if key in SIR_OK and _random() < SIR_RATE:
        text = with_sir(text)
    return text


def part(key, **values):
    """A piece of a longer sentence ('a light breeze'): no capital, never a "sir"."""
    return _choose(PHRASES[key]).format(**values)


def with_sir(text):
    """'Pasta timer, 25 minutes.' -> 'Pasta timer, 25 minutes, sir.'"""
    body = text.rstrip()
    end = body[-1] if body and body[-1] in '.!?' else ''
    return f"{body[:-1] if end else body}, sir{end or '.'}"


def all_variants(key, **values):
    """Every variant of a phrase, filled in (for code that recognizes its own words)."""
    return [variant.format(**values) for variant in PHRASES[key]]
