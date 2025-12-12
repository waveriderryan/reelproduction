import time
import json

from jinja2 import Environment, PackageLoader

from src.ai_video_production.utils.logging_util import get_logger
from src.ai_video_production.utils.data_model import Events
from src.ai_video_production.llm.google_genai import GoogleGenai

logger = get_logger(__name__)


def load_prompt(activity_type: str):
    env = Environment(
        loader=PackageLoader('src.ai_video_production.video_analysis', 'prompt_template'),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template('find_events.jinja')
    context = dict(
        activity_type=activity_type,
    )
    prompt = template.render(context)
    return prompt

async def extract_events(activity_type: str,
                         video_byte: bytes,
                         **kwargs):
    instruction = load_prompt(activity_type)
    genai = GoogleGenai()
    api_key = kwargs.get("api_key")
    response = await genai.ainvoke(video_bytes=[video_byte],
                                   image_bytes=[],
                                   messages=[instruction],
                                   api_key=api_key,
                                   schema=Events)
    data = json.loads(response.text)
    events = Events(**data)
    return events


if __name__ == '__main__':
    video_file_name = input("Enter video file name with path: ")  # e.g. "resource/video/tennis/IMG_0333.mp4"
    start_time = time.time()
    video_bytes = open(video_file_name, 'rb').read()
    print(f"Video loaded: {len(video_bytes)} bytes, took {time.time() - start_time} seconds")
    api_key = input("Enter Google Genai API key: ")

    import asyncio
    events = asyncio.run(extract_events(activity_type="tennis match", video_byte=video_bytes, api_key=api_key))
    print(f"Found events:\n{events}")




