import time
from typing import List

from google import genai
from google.genai import types

from src.production_tool.utils.logging_util import get_logger


logger = get_logger(__name__)


class GoogleGenai:
    """
    https://ai.google.dev/gemini-api/docs/video-understanding
    Only for videos of size <20Mb
    """
    async def ainvoke(self,
                      video_bytes: List[bytes],
                      image_bytes: List[bytes],
                      messages: List[str],
                      model_name: str="gemini-2.5-flash",
                      **kwargs
                      ):

        start_time = time.time()
        api_key = kwargs.get("api_key")
        if api_key is None:
            raise ValueError("api_key is required to setup Google Genai client")
        client = genai.Client(api_key=api_key)

        contents = []
        for video_byte in video_bytes:
            contents.append(
                types.Part(
                    inline_data=types.Blob(
                        data=video_byte,
                        mime_type="video/mp4",
                    )
                )
            )
        for image_byte in image_bytes:
            contents.append(
                types.Part.from_bytes(
                    data=image_byte,
                    mime_type="image/jpeg",
                )
            )
        for message in messages:
            contents.append(
                types.Part(text=message)
            )

        schema = kwargs.get("schema")
        if schema is None:
            response = client.models.generate_content(
                model=f'models/{model_name}',
                contents=types.Content(
                    parts=contents
                )
            )
        else:
            response = client.models.generate_content(
                model=f'models/{model_name}',
                contents=types.Content(
                    parts=contents
                ),
                config={
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                }
            )

        logger.info(f"LLM call finished in {time.time() - start_time} seconds")
        return response
