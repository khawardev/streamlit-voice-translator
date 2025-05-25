import streamlit as st
import asyncio
import threading

from translator import translator_loop 

loop = asyncio.new_event_loop()
thread = None

def run_asyncio_loop():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(translator_loop())

def start_translation():
    global thread
    if not thread or not thread.is_alive():
        thread = threading.Thread(target=run_asyncio_loop)
        thread.start()
        st.success("🟢 Translator is running... Speak to translate to Hindi.")

def stop_translation():
    global loop
    if loop.is_running():
        loop.stop()
        st.warning("🛑 Translator stopped.")

# Streamlit UI
st.set_page_config(page_title="Voice Translator", layout="centered")
st.title("Real-Time Voice Translator")
st.write("This app captures your voice and translates it to **Hindi** in real-time using Gemini.")

start_btn = st.button("Start Translation")
stop_btn = st.button("Stop Translation")

if start_btn:
    start_translation()

if stop_btn:
    stop_translation()
