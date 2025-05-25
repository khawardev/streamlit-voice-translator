import asyncio
import traceback
import pyaudio
from collections import deque
import streamlit as st
from google import genai
from google.genai import types

PROJECT_ID = "sascha-playground-doit"
LOCATION = "us-central1"
MODEL = "gemini-2.0-flash-exp"

client = genai.Client(api_key=st.secrets["gemini"]["api_key"])
FORMAT = pyaudio.paInt16
RECEIVE_SAMPLE_RATE = 24000
SEND_SAMPLE_RATE = 16000
CHUNK_SIZE = 512
CHANNELS = 1

from google.genai.types import (
    LiveConnectConfig,
    SpeechConfig,
    VoiceConfig,
    PrebuiltVoiceConfig,
    Content,
    Part,
)

# Fixed CONFIG - the main issues were:
# 1. system_instruction needs to be a Content object with Parts, not a string
# 2. output_audio_transcription and input_audio_transcription are not valid parameters
CONFIG = LiveConnectConfig(
    response_modalities=["AUDIO"],
    speech_config=SpeechConfig(
        voice_config=VoiceConfig(
            prebuilt_voice_config=PrebuiltVoiceConfig(voice_name="Puck")
        )
    ),
    system_instruction=Content(
        parts=[Part(text="You are a voice translator. Listen to the user's speech in any language and translate it to Hindi. Respond only with the Hindi translation spoken clearly. Do not add any extra commentary or explanation, just provide the direct translation in Hindi.")]
    ),
)

class AudioManager:
    def _init_(self, input_sample_rate=16000, output_sample_rate=24000):
        self.pya = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.audio_queue = deque()
        self.is_playing = False
        self.playback_task = None

    async def initialize(self):
        mic_info = self.pya.get_default_input_device_info()
        print(f"Microphone: {mic_info['name']}")

        self.input_stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=self.input_sample_rate,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=CHUNK_SIZE,
        )

        self.output_stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=self.output_sample_rate,
            output=True,
        )

    def add_audio(self, audio_data):
        self.audio_queue.append(audio_data)
        if self.playback_task is None or self.playback_task.done():
            self.playback_task = asyncio.create_task(self.play_audio())

    async def play_audio(self):
        if self.is_playing:
            return
        self.is_playing = True
        print("🗣 Playing Hindi translation")
        while self.audio_queue:
            try:
                audio_data = self.audio_queue.popleft()
                await asyncio.to_thread(self.output_stream.write, audio_data)
            except Exception as e:
                print(f"Audio error: {e}")
        self.is_playing = False

    def interrupt(self):
        self.audio_queue.clear()
        self.is_playing = False
        if self.playback_task and not self.playback_task.done():
            self.playback_task.cancel()

async def translator_loop():
    audio_manager = AudioManager(
        input_sample_rate=SEND_SAMPLE_RATE, 
        output_sample_rate=RECEIVE_SAMPLE_RATE
    )

    await audio_manager.initialize()
    print("🎤 Voice translator ready - speak to translate to Hindi")

    async with (
        client.aio.live.connect(model=MODEL, config=CONFIG) as session,
        asyncio.TaskGroup() as tg,
    ):
        audio_queue = asyncio.Queue()

        async def listen_for_audio():
            while True:
                data = await asyncio.to_thread(
                    audio_manager.input_stream.read,
                    CHUNK_SIZE,
                    exception_on_overflow=False,
                )
                await audio_queue.put(data)

        async def process_and_send_audio():
            while True:
                data = await audio_queue.get()
                await session.send_realtime_input(
                    media={
                        "data": data,
                        "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}",
                    }
                )
                audio_queue.task_done()

        async def receive_and_play():
            while True:
                input_transcriptions = []
                output_transcriptions = []

                async for response in session.receive():
                    if response.session_resumption_update:
                        update = response.session_resumption_update
                        if update.resumable and update.new_handle:
                            print(f"Session: {update.new_handle}")

                    if response.go_away is not None:
                        print(f"Session ending in: {response.go_away.time_left}")

                    server_content = response.server_content

                    if (
                        hasattr(server_content, "interrupted")
                        and server_content.interrupted
                    ):
                        print("🤐 Interrupted")
                        audio_manager.interrupt()

                    if server_content and server_content.model_turn:
                        for part in server_content.model_turn.parts:
                            if part.inline_data:
                                audio_manager.add_audio(part.inline_data.data)

                    if server_content and server_content.turn_complete:
                        print("✅ Translation complete")

                    # Note: Transcription handling may need adjustment based on actual API response structure
                    # The original code referenced output_transcription and input_transcription
                    # which might not be available without proper configuration
                    output_transcription = getattr(response.server_content, "output_transcription", None)
                    if output_transcription and output_transcription.text:
                        output_transcriptions.append(output_transcription.text)

                    input_transcription = getattr(response.server_content, "input_transcription", None)
                    if input_transcription and input_transcription.text:
                        input_transcriptions.append(input_transcription.text)

                if input_transcriptions:
                    print(f"You said: {''.join(input_transcriptions)}")
                if output_transcriptions:
                    print(f"Hindi translation: {''.join(output_transcriptions)}")

        tg.create_task(listen_for_audio())
        tg.create_task(process_and_send_audio())
        tg.create_task(receive_and_play())